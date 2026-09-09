from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission
from facilities.models import Facility

from .models import (
    CashierSession,
    Invoice,
    Payment,
    PaymentMethod,
    Refund,
    Service,
    ServiceCategory,
    ServicePrice,
)
from .serializers import (
    CashierSessionSerializer,
    DiscountSerializer,
    HandoverSerializer,
    InvoiceSerializer,
    PaymentMethodSerializer,
    PaymentSerializer,
    ReconcileSerializer,
    RecordPaymentSerializer,
    RefundRequestSerializer,
    ServiceCategorySerializer,
    ServicePriceSerializer,
    ServiceSerializer,
    SessionAdjustmentSerializer,
    TillHandoverSerializer,
    VoidSerializer,
)
from .till import (
    UnexplainedVariance,
    hand_over_till,
    reconcile_session,
    record_counts,
)


class _TillClosed(Exception):
    """No open session for this cashier at this facility, checked under a lock."""


class ServiceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ServiceCategory.objects.all()
    serializer_class = ServiceCategorySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "billing.view_servicecategory",
        "retrieve": "billing.view_servicecategory",
        "create": "billing.add_servicecategory",
        "partial_update": "billing.change_servicecategory",
    }


class ServiceViewSet(viewsets.ModelViewSet):
    """Configuration: services and their per-facility prices."""

    queryset = Service.objects.select_related("category").prefetch_related("prices")
    serializer_class = ServiceSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "billing.view_service",
        "retrieve": "billing.view_service",
        "create": "billing.add_service",
        "partial_update": "billing.change_service",
        "set_price": "billing.change_serviceprice",
    }

    @extend_schema(request=ServicePriceSerializer, summary="Set this service's price at "
                                                           "a facility")
    @action(detail=True, methods=["post"], url_path="price", url_name="price")
    def set_price(self, request, pk=None):
        """Superseding rather than editing, so the old price stays auditable."""
        service = self.get_object()
        facility = Facility.objects.filter(pk=request.data.get("facility")).first()
        amount = request.data.get("amount")
        if facility is None or amount is None:
            return Response({"detail": "facility and amount are required."},
                            status=http.HTTP_400_BAD_REQUEST)
        previous = service.prices.filter(facility=facility, is_active=True).first()
        with transaction.atomic():
            if previous:
                previous.is_active = False
                previous.save(update_fields=["is_active"])
            price = ServicePrice.objects.create(
                service=service, facility=facility, amount=Decimal(str(amount))
            )
        AuditEvent.record(
            action="service.price_changed",
            actor=request.user,
            resource=service,
            facility=facility,
            before={"amount": str(previous.amount)} if previous else None,
            after={"amount": str(price.amount), "service": service.code},
            request=request,
        )
        return Response(ServicePriceSerializer(price).data, status=http.HTTP_201_CREATED)


class PaymentMethodViewSet(viewsets.ModelViewSet):
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "billing.view_paymentmethod",
        "retrieve": "billing.view_paymentmethod",
        "create": "billing.add_paymentmethod",
        "partial_update": "billing.change_paymentmethod",
    }


class FacilityScoped:
    def _scope(self, queryset, field="facility_id"):
        user = self.request.user
        if user.is_superuser:
            return queryset
        required = self.required_permissions.get(self.action)
        granted = set(user.facilities_for(required)) if required else set()
        if None in granted:
            return queryset
        return queryset.filter(**{f"{field}__in": [f for f in granted if f is not None]})


class InvoiceViewSet(FacilityScoped, viewsets.ReadOnlyModelViewSet):
    """Invoices are read-only through the API: lines come from clinical events, and
    money changes through payments, discounts, refunds and voids — each with its own
    permission and its own audit trail."""

    queryset = Invoice.objects.none()
    serializer_class = InvoiceSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "billing.view_invoice",
        "retrieve": "billing.view_invoice",
        "outstanding": "billing.view_invoice",
        "discount": "billing.change_invoice",
        "finalise": "billing.change_invoice",
        "void": "billing.void_invoice",
    }

    def get_queryset(self):
        queryset = Invoice.objects.select_related("patient", "facility", "visit"
        ).prefetch_related("items", "payments__method", "payments__refunds",
                           "payments__cashier_session")
        queryset = self._scope(queryset)
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        return queryset

    @extend_schema(request=DiscountSerializer, responses={200: InvoiceSerializer},
                   summary="Apply a discount")
    @action(detail=True, methods=["post"])
    def discount(self, request, pk=None):
        invoice = self.get_object()
        serializer = DiscountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]

        if invoice.is_frozen:
            return Response(
                {"detail": f"{invoice.invoice_number} includes reconciled payments and "
                           f"cannot be changed. Raise an adjusting entry instead."},
                status=http.HTTP_409_CONFLICT,
            )
        if amount > invoice.subtotal:
            return Response({"amount": ["A discount cannot exceed the invoice subtotal."]},
                            status=http.HTTP_400_BAD_REQUEST)

        limit = request.user.discount_limit
        approving = request.user.has_permission("billing.approve_discount", invoice.facility)
        if amount > limit and not approving:
            AuditEvent.record(
                action="invoice.discount_refused",
                actor=request.user,
                outcome=AuditEvent.DENIED,
                resource=invoice,
                patient=invoice.patient,
                facility=invoice.facility,
                after={"requested": str(amount), "limit": str(limit)},
                request=request,
            )
            return Response(
                {"detail": f"Your discount limit is {limit}. A discount of {amount} "
                           f"needs approval from someone holding "
                           f"billing.approve_discount."},
                status=http.HTTP_403_FORBIDDEN,
            )

        before = {"discount_amount": str(invoice.discount_amount),
                  "total": str(invoice.total)}
        invoice.discount_amount = amount
        invoice.discount_reason = serializer.validated_data["reason"]
        invoice.discount_approved_by = request.user if approving else None
        invoice.save(update_fields=["discount_amount", "discount_reason",
                                    "discount_approved_by"])
        invoice.refresh_from_db()
        AuditEvent.record(
            action="invoice.discounted",
            actor=request.user,
            resource=invoice,
            patient=invoice.patient,
            facility=invoice.facility,
            before=before,
            after={"discount_amount": str(invoice.discount_amount),
                   "total": str(invoice.total), "within_limit": amount <= limit},
            reason=invoice.discount_reason,
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=invoice.pk)).data)

    @extend_schema(request=None, responses={200: InvoiceSerializer},
                   summary="Finalise the invoice")
    @action(detail=True, methods=["post"])
    def finalise(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status != Invoice.DRAFT:
            return Response({"detail": f"Already {invoice.status}."},
                            status=http.HTTP_409_CONFLICT)
        if not invoice.items.exists():
            return Response({"detail": "Nothing has been charged to this invoice."},
                            status=http.HTTP_409_CONFLICT)
        invoice.status = Invoice.FINALISED
        invoice.finalised_at = timezone.now()
        invoice.save(update_fields=["status", "finalised_at"])
        AuditEvent.record(
            action="invoice.finalised",
            actor=request.user, resource=invoice, patient=invoice.patient,
            facility=invoice.facility,
            after={"total": str(invoice.total), "items": invoice.items.count()},
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=invoice.pk)).data)

    @extend_schema(request=VoidSerializer, responses={200: InvoiceSerializer},
                   summary="Void an invoice (reason required)")
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        invoice = self.get_object()
        serializer = VoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if invoice.is_frozen:
            return Response(
                {"detail": "This invoice includes reconciled payments and cannot be "
                           "voided."},
                status=http.HTTP_409_CONFLICT,
            )
        if invoice.payments.exists():
            return Response(
                {"detail": "Refund the payments on this invoice before voiding it."},
                status=http.HTTP_409_CONFLICT,
            )
        invoice.status = Invoice.VOID
        invoice.voided_at = timezone.now()
        invoice.void_reason = serializer.validated_data["reason"]
        invoice.save(update_fields=["status", "voided_at", "void_reason"])
        AuditEvent.record(
            action="invoice.voided",
            actor=request.user, resource=invoice, patient=invoice.patient,
            facility=invoice.facility,
            reason=invoice.void_reason,
            after={"total": str(invoice.total)},
            request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=invoice.pk)).data)

    @extend_schema(summary="Invoices with an outstanding balance")
    @action(detail=False, methods=["get"])
    def outstanding(self, request):
        rows = [
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "patient_name": invoice.patient.full_name,
                "hospital_number": invoice.patient.hospital_number,
                "total": str(invoice.total),
                "amount_paid": str(invoice.amount_paid),
                "balance": str(invoice.balance),
                "status": invoice.status,
            }
            for invoice in self.get_queryset().exclude(status=Invoice.VOID)
            if invoice.balance > 0
        ]
        return Response(rows)


class CashierSessionViewSet(FacilityScoped, viewsets.ModelViewSet):
    queryset = CashierSession.objects.none()
    serializer_class = CashierSessionSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "billing.view_cashiersession",
        "retrieve": "billing.view_cashiersession",
        "create": "billing.add_cashiersession",
        "close": "billing.change_cashiersession",
        "reconcile": "billing.reconcile_cashiersession",
        "adjust": "billing.adjust_cashiersession",
        "handover": "billing.receive_till",
    }

    def get_queryset(self):
        return self._scope(
            CashierSession.objects.select_related("cashier", "facility")
            .prefetch_related(
                "payments", "counts__method", "adjustments__raised_by",
                "adjustments__method",
            )
        )

    def facility_for_permission(self, request):
        if self.action == "create":
            return Facility.objects.filter(pk=request.data.get("facility")).first()
        return None

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                session = serializer.save(cashier=request.user)
        except IntegrityError:
            return Response(
                {"detail": "You already have an open session at this facility."},
                status=http.HTTP_409_CONFLICT,
            )
        AuditEvent.record(
            action="cashier_session.opened", actor=request.user, resource=session,
            facility=session.facility,
            after={"opening_float": str(session.opening_float)}, request=request,
        )
        return Response(self.get_serializer(session).data, status=http.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: CashierSessionSerializer},
                   summary="Close the session to further payments")
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        session = self.get_object()
        with transaction.atomic():
            # The other half of the payment race: whichever of the two takes the
            # lock first wins cleanly, and the loser sees a settled status.
            session = CashierSession.objects.select_for_update().get(pk=session.pk)
            if session.status != CashierSession.OPEN:
                return Response({"detail": f"Session is already {session.status}."},
                                status=http.HTTP_409_CONFLICT)
            session.status = CashierSession.CLOSED
            session.closed_at = timezone.now()
            session.save(update_fields=["status", "closed_at"])
        AuditEvent.record(
            action="cashier_session.closed", actor=request.user, resource=session,
            facility=session.facility,
            after={"expected_total": str(session.expected_total())}, request=request,
        )
        return Response(self.get_serializer(session).data)

    @extend_schema(request=ReconcileSerializer, responses={200: CashierSessionSerializer},
                   summary="Reconcile the session — this freezes its money")
    @action(detail=True, methods=["post"])
    def reconcile(self, request, pk=None):
        session = self.get_object()
        serializer = ReconcileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if session.status == CashierSession.RECONCILED:
            # Telling somebody to close a session they have already signed off
            # sends them looking for a button that is not there.
            return Response(
                {"detail": "This session is already signed off and its money is "
                           "frozen. Record a correction against it instead."},
                status=http.HTTP_409_CONFLICT,
            )
        if session.status != CashierSession.CLOSED:
            return Response({"detail": "Close the session before signing it off."},
                            status=http.HTTP_409_CONFLICT)

        try:
            with transaction.atomic():
                session = CashierSession.objects.select_for_update().get(pk=session.pk)
                record_counts(session, serializer.validated_data["counts"])
                problems = session.unexplained_variances()
                if problems:
                    # Refusing is the point of the endpoint, so it must happen
                    # before anything is committed.
                    raise UnexplainedVariance(problems)
                reconcile_session(
                    session,
                    by=request.user,
                    note=serializer.validated_data["variance_note"],
                )
        except UnexplainedVariance as refusal:
            return Response({"unexplained": refusal.problems},
                            status=http.HTTP_400_BAD_REQUEST)

        AuditEvent.record(
            action="cashier_session.reconciled", actor=request.user, resource=session,
            facility=session.facility,
            after={"expected": str(session.expected_total()),
                   "counted": str(session.counted_total),
                   "net_variance": str(session.net_variance),
                   "by_method": session.variance_summary_for_audit()},
            reason=session.variance_note, request=request,
        )
        return Response(self.get_serializer(session).data)

    @extend_schema(request=SessionAdjustmentSerializer,
                   responses={201: SessionAdjustmentSerializer},
                   summary="Correct a reconciled session with a new entry")
    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        """AC-141. The reconciled session is not touched; this sits beside it."""
        session = self.get_object()
        if session.status != CashierSession.RECONCILED:
            return Response(
                {"detail": "Only a reconciled session is corrected by adjustment. "
                           "An open or closed session is reconciled instead."},
                status=http.HTTP_409_CONFLICT,
            )
        serializer = SessionAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = serializer.save(session=session, raised_by=request.user)
        AuditEvent.record(
            action="cashier_session.adjusted", actor=request.user, resource=adjustment,
            facility=session.facility,
            after={"session": str(session.pk), "kind": adjustment.kind,
                   "amount": str(adjustment.amount)},
            reason=adjustment.reason, request=request,
        )
        return Response(SessionAdjustmentSerializer(adjustment).data,
                        status=http.HTTP_201_CREATED)

    @extend_schema(request=HandoverSerializer, responses={201: TillHandoverSerializer},
                   summary="Hand the till to the cashier taking over")
    @action(detail=True, methods=["post"], permission_classes=[HasPermission])
    def handover(self, request, pk=None):
        """AC-142. Called by the *incoming* cashier, so both names are real.

        The outgoing cashier cannot name who took the money over: a signature
        one person supplies for two people is not a second signature. The
        person receiving the till calls this, and their session is the one that
        opens.
        """
        session = self.get_object()
        serializer = HandoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if session.status != CashierSession.OPEN:
            return Response({"detail": f"That till is already {session.status}."},
                            status=http.HTTP_409_CONFLICT)
        if session.cashier_id == request.user.pk:
            return Response(
                {"detail": "A till is handed to somebody else. Close your own "
                           "session instead."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if CashierSession.objects.filter(
            cashier=request.user, facility=session.facility,
            status=CashierSession.OPEN,
        ).exists():
            return Response(
                {"detail": "You already have an open session at this facility. "
                           "Close it before receiving another till."},
                status=http.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                session = CashierSession.objects.select_for_update().get(pk=session.pk)
                if session.status != CashierSession.OPEN:
                    # Re-read under the lock: the outgoing cashier may have
                    # closed it while this request was in flight.
                    raise _TillClosed(f"That till is already {session.status}.")
                record_counts(session, serializer.validated_data["counts"])
                problems = session.unexplained_variances()
                if problems:
                    raise UnexplainedVariance(problems)
                handover = hand_over_till(
                    session,
                    to_user=request.user,
                    float_handed=serializer.validated_data["float_handed"],
                    note=serializer.validated_data["note"],
                )
        except UnexplainedVariance as refusal:
            return Response({"unexplained": refusal.problems},
                            status=http.HTTP_400_BAD_REQUEST)
        except _TillClosed as closed:
            return Response({"detail": str(closed)}, status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="cashier_session.handed_over", actor=request.user,
            resource=handover, facility=session.facility,
            after={"from_session": str(session.pk),
                   "to_session": str(handover.to_session_id),
                   "float_handed": str(handover.float_handed),
                   "handed_by": session.cashier.email,
                   "received_by": request.user.email},
            reason=handover.note, request=request,
        )
        return Response(TillHandoverSerializer(handover).data,
                        status=http.HTTP_201_CREATED)


class PaymentViewSet(FacilityScoped, viewsets.ModelViewSet):
    queryset = Payment.objects.none()
    serializer_class = PaymentSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]

    required_permissions = {
        "list": "billing.view_payment",
        "retrieve": "billing.view_payment",
        "create": "billing.add_payment",
        "receipt": "billing.view_payment",
        "refund": "billing.issue_refund",
    }

    def get_queryset(self):
        return self._scope(
            Payment.objects.select_related(
                "invoice__patient", "invoice__facility", "method", "received_by",
                "cashier_session",
            ).prefetch_related("refunds__issued_by"),
            field="invoice__facility_id",
        )

    def facility_for_permission(self, request):
        if self.action == "create":
            invoice = Invoice.objects.filter(pk=request.data.get("invoice")).first()
            return invoice.facility if invoice else None
        return None

    def create(self, request, *args, **kwargs):
        """Record a payment, at most once per idempotency key."""
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        existing = Payment.objects.filter(
            idempotency_key=data["idempotency_key"]
        ).first()
        if existing is not None:
            # A retry, not a second payment. Same key, same receipt.
            return Response(self.get_serializer(existing).data, status=http.HTTP_200_OK)

        invoice = Invoice.objects.filter(pk=data["invoice"]).first()
        method = PaymentMethod.objects.filter(pk=data["method"], is_active=True).first()
        if invoice is None or method is None:
            return Response({"detail": "Unknown invoice or payment method."},
                            status=http.HTTP_400_BAD_REQUEST)
        if invoice.status == Invoice.VOID:
            return Response({"detail": "That invoice is void."},
                            status=http.HTTP_409_CONFLICT)
        if method.requires_reference and not data["reference"]:
            return Response({"reference": [f"{method.name} payments need a reference."]},
                            status=http.HTTP_400_BAD_REQUEST)
        if data["amount"] <= 0:
            return Response({"amount": ["A payment must be positive."]},
                            status=http.HTTP_400_BAD_REQUEST)
        if data["amount"] > invoice.balance:
            return Response(
                {"amount": [f"That is more than the outstanding balance of "
                            f"{invoice.balance}."]},
                status=http.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # Locked and re-read inside the transaction: a close running
                # between the check and the insert would otherwise post money
                # into a session somebody is already counting. Guarantee 5.
                session = CashierSession.objects.select_for_update().filter(
                    cashier=request.user, facility=invoice.facility,
                    status=CashierSession.OPEN,
                ).first()
                if session is None:
                    raise _TillClosed
                payment = Payment.objects.create(
                    invoice=invoice, cashier_session=session, method=method,
                    amount=data["amount"], reference=data["reference"],
                    idempotency_key=data["idempotency_key"], received_by=request.user,
                )
                invoice.refresh_from_db()
                if invoice.balance <= 0 and invoice.status != Invoice.PAID:
                    invoice.status = Invoice.PAID
                    invoice.save(update_fields=["status"])
        except _TillClosed:
            return Response(
                {"detail": "Open a cashier session before taking payments."},
                status=http.HTTP_409_CONFLICT,
            )
        except IntegrityError:
            # Lost a race on the same key; return the winner rather than erroring.
            payment = Payment.objects.get(idempotency_key=data["idempotency_key"])
            return Response(self.get_serializer(payment).data, status=http.HTTP_200_OK)

        AuditEvent.record(
            action="payment.received", actor=request.user, resource=invoice,
            patient=invoice.patient, facility=invoice.facility,
            after={"receipt": payment.receipt_number, "amount": str(payment.amount),
                   "method": method.code, "balance_after": str(invoice.balance)},
            request=request,
        )
        return Response(self.get_serializer(payment).data, status=http.HTTP_201_CREATED)

    @extend_schema(summary="Receipt, and a reprint counter")
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        """A reprint is identical to the original and is logged as a reprint."""
        payment = self.get_object()
        is_reprint = payment.reprint_count > 0 or request.query_params.get(
            "reprint"
        ) == "true"
        if request.query_params.get("reprint") == "true":
            Payment.objects.filter(pk=payment.pk).update(
                reprint_count=payment.reprint_count + 1
            )
            AuditEvent.record(
                action="receipt.reprinted", actor=request.user, resource=payment.invoice,
                patient=payment.invoice.patient, facility=payment.invoice.facility,
                after={"receipt": payment.receipt_number,
                       "reprint_number": payment.reprint_count + 1},
                request=request,
            )
        invoice = payment.invoice
        return Response({
            "receipt_number": payment.receipt_number,
            "issued_at": payment.received_at,
            "patient_name": invoice.patient.full_name,
            "hospital_number": invoice.patient.hospital_number,
            "invoice_number": invoice.invoice_number,
            "facility": invoice.facility.name,
            "items": [
                {"description": item.description, "quantity": item.quantity,
                 "unit_price": str(item.unit_price), "amount": str(item.amount)}
                for item in invoice.items.all() if not item.is_cancelled
            ],
            "subtotal": str(invoice.subtotal),
            "discount": str(invoice.discount_amount),
            "tax": str(invoice.tax_amount),
            "total": str(invoice.total),
            "amount_paid": str(payment.amount),
            "method": payment.method.name,
            "reference": payment.reference,
            "received_by": payment.received_by.full_name,
            "balance_after": str(invoice.balance),
            "is_reprint": is_reprint,
        })

    @extend_schema(request=RefundRequestSerializer, responses={200: PaymentSerializer},
                   summary="Refund against this payment (reason required)")
    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        payment = self.get_object()
        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]

        if amount <= 0:
            return Response({"amount": ["A refund must be positive."]},
                            status=http.HTTP_400_BAD_REQUEST)
        refundable = payment.amount - payment.amount_refunded
        if amount > refundable:
            return Response(
                {"amount": [f"Only {refundable} remains refundable on receipt "
                            f"{payment.receipt_number}."]},
                status=http.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                session = CashierSession.objects.select_for_update().filter(
                    cashier=request.user, facility=payment.invoice.facility,
                    status=CashierSession.OPEN,
                ).first()
                if session is None:
                    raise _TillClosed
                refund = Refund.objects.create(
                    payment=payment, amount=amount,
                    reason=serializer.validated_data["reason"],
                    cashier_session=session, issued_by=request.user,
                )
                invoice = payment.invoice
                invoice.refresh_from_db()
                if invoice.balance > 0 and invoice.status == Invoice.PAID:
                    invoice.status = Invoice.FINALISED
                    invoice.save(update_fields=["status"])
        except _TillClosed:
            return Response({"detail": "Open a cashier session before issuing refunds."},
                            status=http.HTTP_409_CONFLICT)

        AuditEvent.record(
            action="payment.refunded", actor=request.user, resource=payment.invoice,
            patient=payment.invoice.patient, facility=payment.invoice.facility,
            before={"receipt": payment.receipt_number,
                    "original_amount": str(payment.amount)},
            after={"refund_reference": refund.reference, "amount": str(refund.amount),
                   "balance_after": str(payment.invoice.balance)},
            reason=refund.reason, request=request,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=payment.pk)).data)
