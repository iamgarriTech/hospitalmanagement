> **This document is the domain specification, not the build order.**
> It describes what a mature system covers. For what is being built now, in what order,
> and against which acceptance criteria, see [docs/roadmap.md](docs/roadmap.md).
> Standing constraints are in [CLAUDE.md](CLAUDE.md); decisions in
> [docs/decisions.md](docs/decisions.md).

Build a complete, production-grade Hospital Management System intended for real-world hospital use and eventual open-source release.

Take ownership of the product from architecture through implementation.

I am intentionally not prescribing frameworks, programming languages, database technologies, folder structures, libraries, deployment platforms, architectural patterns, or implementation details. Make those decisions yourself based on what best serves the product.

Do not treat this as a CRUD application, admin dashboard template, school project, prototype, or proof of concept.

The goal is a serious healthcare platform capable of supporting actual hospital operations.

# PRODUCT VISION

Build a modern Hospital Management System that can be used by:

* Small clinics
* Private hospitals
* Specialist hospitals
* Diagnostic centres
* Multi-department hospitals
* Multi-branch healthcare organizations

The product should be modular enough that smaller facilities can use only what they need while larger organizations can enable more capabilities.

The system should eventually be credible as a serious open-source alternative to proprietary hospital management software.

# CORE PRINCIPLES

The platform must prioritize:

* Security
* Patient safety
* Privacy
* Reliability
* Data integrity
* Auditability
* Clinical usability
* Accessibility
* Modularity
* Extensibility
* Maintainability
* Performance
* Interoperability
* Open-source friendliness

Hospital staff often work quickly and under pressure.

The system should reduce unnecessary steps, reduce opportunities for mistakes, and make important information easy to find.

# USERS AND ACCESS CONTROL

Support hospital users such as:

* Super Administrator
* Hospital Administrator
* Doctor
* Consultant
* Nurse
* Receptionist
* Pharmacist
* Laboratory Scientist
* Laboratory Technician
* Radiologist
* Radiographer
* Cashier
* Accountant
* Medical Records Officer
* Inventory Officer
* Theatre Staff
* Department Head
* Facility Manager
* Patient
* Other configurable staff roles

Do not permanently hard-code permissions around these roles.

Hospitals should be able to create roles and assign granular permissions.

Permissions should account for actions such as:

* Viewing records
* Creating records
* Editing records
* Approving records
* Cancelling records
* Dispensing medication
* Recording payments
* Issuing refunds
* Managing inventory
* Viewing financial information
* Viewing sensitive clinical information
* Exporting information
* Managing users
* Managing permissions
* Accessing reports

Sensitive actions should be auditable.

# ORGANIZATION AND FACILITY STRUCTURE

Support structures such as:

Organization

Hospital

Branch

Facility

Department

Unit

Clinic

Ward

Room

Bed

Pharmacy

Laboratory

Store

Theatre

Imaging department

Allow different facilities to operate independently while still supporting organization-level reporting when necessary.

# PATIENT MANAGEMENT

Support the complete patient lifecycle.

Include:

* Patient registration
* Unique hospital/patient number
* Demographic information
* Contact information
* Address
* Emergency contacts
* Next of kin
* Patient photograph
* Blood group
* Genotype where applicable
* Allergies
* Chronic conditions
* Relevant medical history
* Insurance/HMO information
* Patient status
* Patient search
* Patient merging
* Duplicate patient detection
* Patient documents
* Patient notes
* Visit history
* Clinical history
* Billing history
* Prescription history
* Investigation history
* Admission history

Provide a unified patient profile.

Important clinical information should be immediately visible when appropriate.

# PATIENT IDENTIFICATION

Avoid dangerous duplicate records.

Support searching patients by appropriate identifiers such as:

* Hospital number
* Name
* Phone number
* Date of birth
* Email
* Other configured identifiers

Provide mechanisms for handling suspected duplicate records safely.

# APPOINTMENTS

Support:

* Appointment booking
* Walk-in appointments
* Rescheduling
* Cancellation
* Appointment confirmation
* Follow-up appointments
* Recurring appointments where appropriate
* Doctor schedules
* Clinic schedules
* Department schedules
* Availability
* Appointment status
* Check-in
* Waiting lists
* Queues
* Appointment history
* Appointment reminders
* Calendar views

# RECEPTION AND FRONT DESK

Reception staff should be able to efficiently:

* Register new patients
* Find returning patients
* Book appointments
* Check patients in
* Confirm payment requirements
* Assign clinics
* Direct patients to departments
* Add patients to queues
* Track patient movement
* View relevant appointment information

# PATIENT QUEUE

Provide a practical queue system supporting:

* Waiting
* Checked in
* Called
* In consultation
* Sent for investigation
* Sent to pharmacy
* Sent for billing
* Completed
* Cancelled
* Other appropriate workflow states

The queue should reflect actual patient movement rather than functioning as a simple list.

# ELECTRONIC MEDICAL RECORD / CLINICAL CARE

Doctors and authorized clinicians should be able to conduct consultations comprehensively.

Support:

* Encounters
* Presenting complaint
* History of presenting complaint
* Past medical history
* Surgical history
* Family history
* Social history
* Relevant medication history
* Allergies
* Vital signs
* Examination findings
* Clinical notes
* Diagnoses
* Differential diagnoses
* Problem lists
* Treatment plans
* Prescriptions
* Laboratory requests
* Imaging requests
* Procedures
* Referrals
* Follow-up plans
* Medical certificates
* Attachments
* Encounter summaries

Clinical records should preserve history correctly.

Changing today's diagnosis should not silently rewrite what was recorded during an older consultation.

# CLINICAL RECORD VERSIONING

Important clinical information should maintain appropriate historical context.

Where necessary, preserve:

* Previous values
* Who changed information
* When it was changed
* Why it was changed
* Corrected/amended versions

Clinical records should not simply disappear because someone edited them.

# VITAL SIGNS

Support appropriate measurements including:

* Temperature
* Blood pressure
* Pulse
* Respiratory rate
* Oxygen saturation
* Weight
* Height
* BMI
* Blood glucose where applicable
* Pain score
* Other configurable observations

Allow vital trends to be viewed over time.

# NURSING

Support workflows such as:

* Nursing assessment
* Nursing notes
* Vital observations
* Medication administration
* Intake and output
* Patient monitoring
* Care plans where appropriate
* Escalation of concerns
* Shift-related documentation
* Inpatient observations

# MEDICATION ADMINISTRATION

For inpatient care, provide a reliable medication administration workflow.

Support concepts such as:

* Medication prescribed
* Scheduled administration
* Administered
* Missed
* Delayed
* Refused
* Withheld
* Discontinued

Maintain appropriate documentation of who administered medication and when.

# MEDICATION SAFETY

Medication workflows should account for patient safety.

The system should be capable of warning clinicians about relevant issues such as:

* Known allergies
* Potential duplicate medication
* Inappropriate duplication
* Relevant contraindication information where available
* Dose-related concerns where appropriate
* Medication availability

Warnings should assist clinicians without making the interface unusable through excessive alerts.

# ADMISSIONS

Support:

* Admission requests
* Admission
* Admission reason
* Admission diagnosis
* Ward allocation
* Room allocation
* Bed allocation
* Bed transfers
* Ward transfers
* Admission history
* Responsible consultant
* Inpatient clinical notes
* Nursing notes
* Orders
* Medication administration
* Daily reviews
* Procedures
* Investigations
* Discharge planning
* Discharge
* Discharge summary
* Discharge diagnosis
* Discharge medication
* Follow-up instructions
* Final billing

# BED MANAGEMENT

Provide a hospital-wide view of:

* Available beds
* Occupied beds
* Reserved beds
* Beds being cleaned
* Beds unavailable for maintenance
* Ward capacity
* Current patient assignment

Bed movement history should be traceable.

# EMERGENCY DEPARTMENT

Support emergency workflows including:

* Rapid patient registration
* Unknown/unidentified patient handling where appropriate
* Triage
* Severity classification
* Emergency observations
* Clinical assessment
* Emergency orders
* Procedures
* Medication
* Investigations
* Monitoring
* Admission
* Transfer
* Referral
* Discharge
* Outcome

Emergency workflows should prioritize speed without compromising traceability.

# LABORATORY

Build a complete laboratory workflow.

Support:

* Laboratory test catalogue
* Test categories
* Test panels
* Test pricing
* Laboratory orders
* Specimen requirements
* Specimen collection
* Sample labels
* Sample identifiers
* Sample tracking
* Collection status
* Processing status
* Result entry
* Multiple result parameters
* Units
* Reference ranges
* Abnormal result indicators
* Critical result indicators
* Clinical comments
* Result verification
* Result approval
* Corrections/amendments
* Result history
* Printable reports
* Clinician access to completed results

Support tests containing multiple measurements rather than assuming one test equals one result.

# CRITICAL RESULTS

The system should have an appropriate way of flagging critical laboratory or clinical findings that may require urgent attention.

Important acknowledgements or communication should be traceable where appropriate.

# RADIOLOGY AND IMAGING

Support:

* Imaging catalogue
* Imaging orders
* Scheduling
* Imaging status
* Findings
* Reports
* Report approval
* Amendments
* Attachments
* Clinician access to reports
* Imaging history

The architecture should allow future integration with:

* PACS
* RIS
* DICOM-based systems
* External imaging providers

# PHARMACY

Support:

* Medication catalogue
* Generic names
* Brand names where required
* Categories
* Strength
* Dosage form
* Units
* Route
* Pricing
* Prescription review
* Prescription status
* Dispensing
* Partial dispensing
* Dispensing history
* Batch tracking
* Expiry dates
* Stock availability
* Reorder levels
* Stock adjustments
* Returned medication where appropriate

Dispensing medication should appropriately affect pharmacy inventory.

# INVENTORY AND STORES

Support general hospital inventory.

Include:

* Items
* Categories
* Units
* Suppliers
* Store locations
* Stock levels
* Purchase requests
* Purchase orders
* Goods received
* Stock movements
* Internal transfers
* Batch numbers
* Expiry dates
* Stock adjustments
* Damaged stock
* Expired stock
* Returned stock
* Reorder levels
* Low-stock alerts
* Expiry alerts
* Inventory history

Every meaningful inventory movement should be traceable.

# PROCUREMENT

Provide a foundation for:

* Suppliers
* Purchase requests
* Approval workflow
* Purchase orders
* Goods received
* Supplier invoices
* Procurement history

Do not turn the product into a full enterprise ERP unless necessary.

# BILLING

Provide comprehensive hospital billing.

Support charges arising from:

* Registration
* Consultations
* Admissions
* Bed usage
* Laboratory
* Imaging
* Pharmacy
* Procedures
* Theatre
* Consumables
* Other hospital services

Support:

* Invoices
* Invoice items
* Draft bills
* Finalized bills
* Discounts
* Taxes where applicable
* Deposits
* Partial payments
* Multiple payments
* Outstanding balances
* Credit
* Refunds
* Receipts
* Payment methods
* Payment history
* Cashier sessions
* Daily reconciliation
* Voids/cancellations with appropriate authorization

Financial records should not silently change after reconciliation.

# FINANCIAL INTEGRITY

Design financial workflows so important events remain traceable.

Protect against:

* Duplicate charges
* Duplicate payment recording
* Unauthorized discounts
* Unauthorized refunds
* Silent invoice modification
* Deletion of reconciled financial activity

# INSURANCE / HMO

Support healthcare insurance workflows.

Include:

* Insurance providers
* HMO providers
* Plans
* Patient policies
* Policy numbers
* Coverage information
* Eligibility information
* Covered services
* Exclusions
* Co-pay
* Preauthorization
* Authorization references
* Claims
* Claim items
* Claim submission status
* Rejected claims
* Resubmission
* Insurance invoices
* Provider payments
* Reconciliation

Nigeria should be a strong initial use case, but do not make the architecture dependent on one country's insurance model.

# PROCEDURES

Support:

* Procedure catalogue
* Procedure requests
* Scheduling
* Procedure team
* Procedure notes
* Consumables
* Medication
* Findings
* Outcomes
* Billing
* Procedure history

# THEATRE / SURGERY

Support:

* Theatre rooms
* Theatre schedules
* Surgical procedures
* Surgical team
* Pre-operative information
* Operation notes
* Anaesthesia-related records where appropriate
* Consumables
* Medication usage
* Post-operative notes
* Recovery
* Outcomes
* Billing

# MATERNITY

Provide a modular maternity capability supporting areas such as:

* Pregnancy records
* Antenatal visits
* Estimated delivery date
* Maternal observations
* Delivery records
* Delivery method
* Mother/baby linking
* Birth details
* Postnatal records

Maternity functionality may remain modular where specialization becomes significant.

# REFERRALS

Support:

* Internal referrals
* External referrals
* Referral reasons
* Referring clinician
* Receiving clinician/facility
* Referral status
* Referral notes
* Relevant records
* Referral outcome

# MEDICAL RECORDS

Support:

* Patient documents
* Medical reports
* Referral letters
* Discharge summaries
* Medical certificates
* Visit summaries
* Attachments
* Record printing
* Appropriate record export
* Record access history

# PATIENT CONSENT

Provide a foundation for recording and respecting relevant patient consent.

Examples may include:

* Treatment consent
* Procedure consent
* Data-sharing consent
* Research consent
* Communication preferences

Consent records should have appropriate timestamps and history.

# PRIVACY

Patient information is highly sensitive.

Support appropriate privacy controls around:

* Clinical data
* Financial data
* Sensitive diagnoses
* Patient documents
* Employee access
* Patient portal access
* Data exports

Access should follow least-privilege principles.

# BREAK-GLASS ACCESS

Consider situations where emergency access to otherwise restricted information may legitimately be required.

Such access should be exceptional, clearly recorded, and auditable.

# STAFF MANAGEMENT

Support relevant staff information such as:

* Staff profile
* Staff identifier
* Professional role
* Department
* Specialty
* Facility
* Status
* Schedules
* System access

Do not turn the HMS into a full payroll or HR platform unless operationally necessary.

# DEPARTMENTS

Support configurable hospital departments and service units.

Examples may include:

* General outpatient
* Internal medicine
* Surgery
* Paediatrics
* Obstetrics and gynaecology
* Pharmacy
* Laboratory
* Radiology
* Emergency
* Theatre
* Physiotherapy
* Dentistry
* Ophthalmology

Do not hard-code the system around this list.

# NOTIFICATIONS

Provide a notification capability capable of supporting:

* Appointment reminders
* Follow-up reminders
* Laboratory result notifications
* Imaging result notifications
* Relevant clinical alerts
* Low stock
* Expiring stock
* Billing events
* Insurance events
* Staff notifications

Allow multiple delivery channels to be added over time.

# TASKS AND INTERNAL WORKFLOW

Where useful, allow staff to manage operational tasks such as:

* Follow-ups
* Pending investigations
* Pending approvals
* Patient callbacks
* Stock actions
* Administrative tasks

# DASHBOARDS

Dashboards should be role-aware.

A:

* Doctor
* Nurse
* Receptionist
* Pharmacist
* Laboratory scientist
* Cashier
* Hospital administrator

should not all see the same dashboard.

Show information that helps each role perform their work.

Avoid meaningless statistics and decorative charts.

# REPORTING AND ANALYTICS

Provide useful reporting around areas including:

* Patient registrations
* Patient visits
* Appointments
* Waiting times
* Admissions
* Length of stay
* Bed occupancy
* Department activity
* Clinician activity
* Laboratory activity
* Imaging activity
* Pharmacy activity
* Medication dispensing
* Inventory
* Stock usage
* Expiring stock
* Revenue
* Payments
* Outstanding balances
* Discounts
* Refunds
* Insurance claims
* Common services
* Diagnoses where appropriate

Allow filtering by relevant dimensions including:

* Date
* Facility
* Department
* Clinician
* Service
* Payment method
* Insurance provider

Reports should respect access permissions.

# PATIENT PORTAL

Provide a patient-facing experience capable of supporting:

* Patient profile
* Appointments
* Appointment requests
* Visit history
* Prescriptions
* Laboratory results
* Imaging reports
* Bills
* Payments
* Receipts
* Relevant medical documents
* Communication preferences

Patients must only see information they are permitted to access.

# AUDIT TRAIL

Auditability is a core product requirement.

Important actions should be traceable.

Examples include:

* Login
* Failed login attempts
* Patient record access
* Record creation
* Record modification
* Record correction
* Diagnosis changes
* Prescription changes
* Medication dispensing
* Medication administration
* Lab result changes
* Result approval
* Billing changes
* Payments
* Refunds
* Stock movements
* Stock adjustments
* Role changes
* Permission changes
* Exports
* Emergency access

For meaningful events, it should be possible to determine:

* What happened
* Who performed the action
* When it happened
* Which patient or resource was affected
* Relevant previous/new values where appropriate

# AUDIT LOG INTEGRITY

Treat audit history as security-critical information.

Normal application users should not be able to silently rewrite or remove their historical actions.

# SECURITY

Treat healthcare information as highly sensitive.

The product must appropriately address:

* Authentication
* Authorization
* Password security
* Session security
* Account recovery
* Brute-force protection
* Privilege escalation
* Input validation
* File uploads
* API access
* Sensitive data
* Data exposure
* Common application vulnerabilities
* Security logging
* Secrets management
* Secure configuration
* Abuse prevention

Security should be part of the architecture rather than something added at the end.

# DATA INTEGRITY

Protect against situations such as:

* Duplicate patients
* Duplicate charges
* Duplicate dispensing
* Negative inventory caused by invalid activity
* Broken patient history
* Orphaned records
* Unauthorized modifications
* Inconsistent billing
* Missing audit information
* Invalid clinical state transitions

# DATA RETENTION

Design the platform so healthcare organizations can establish appropriate policies for:

* Record retention
* Archiving
* Legal holds
* Data deletion where legally permitted
* Deactivation rather than destructive deletion
* Backup retention

Do not assume all healthcare records can simply be permanently deleted.

# BACKUPS AND DISASTER RECOVERY

The product should be designed with serious healthcare operations in mind.

Account for:

* Backups
* Restoration
* Disaster recovery
* Recovery from infrastructure failure
* Protection against accidental data loss
* Appropriate operational documentation

Do not assume deployment will always run perfectly.

# SYSTEM RELIABILITY

Important hospital operations should fail safely.

Where appropriate, consider:

* Transaction integrity
* Concurrent activity
* Idempotency
* Retry behaviour
* Duplicate submissions
* Network interruptions
* Partial failures

# INTEROPERABILITY

Keep healthcare interoperability in mind from the beginning.

The architecture should leave room for integration with standards and systems such as:

* FHIR
* HL7
* DICOM
* PACS
* External laboratories
* External pharmacies
* Insurance providers
* Payment providers
* Government healthcare systems
* SMS providers
* Email providers

Do not build every integration immediately.

Avoid architectural choices that would make future interoperability unnecessarily difficult.

# API AND INTEGRATION READINESS

The platform should have clear boundaries that allow authorized third-party systems to interact with relevant functionality in the future.

Integration must respect:

* Authentication
* Permissions
* Patient privacy
* Audit requirements
* Data integrity

# IMPORT / EXPORT

Hospitals should eventually be able to safely import or export appropriate information.

This may include:

* Patients
* Services
* Medications
* Inventory
* Reports
* Billing information
* Clinical information where permitted

Do not allow bulk export capabilities to bypass privacy and permission controls.

# MULTI-FACILITY SUPPORT

Architect the system so it can support:

* One hospital
* Multiple branches
* Hospital groups
* Independent departments
* Multiple pharmacies
* Multiple laboratories
* Multiple stores
* Multiple wards

Different facilities may have different:

* Prices
* Services
* Inventory
* Staff
* Schedules
* Departments
* Billing configuration

Organization-level management should still be possible where authorized.

# TENANT ISOLATION

If the product supports multiple independent organizations, data belonging to one organization must not accidentally become accessible to another organization.

Treat tenant separation as a security boundary.

# LOCALIZATION

Avoid assumptions that make the platform usable only in one country.

Allow future support for:

* Multiple currencies
* Different date formats
* Different time formats
* Time zones
* Phone formats
* Address formats
* Configurable terminology
* Multiple languages
* Different insurance structures
* Different tax structures

Nigeria can be the initial deployment context without making the product Nigeria-only.

# CONFIGURATION

Hospital administrators should be able to configure important operational information without modifying source code.

Examples include:

* Organization details
* Facilities
* Departments
* Clinics
* Wards
* Rooms
* Beds
* Services
* Prices
* Laboratory tests
* Medications
* Units
* Inventory items
* Payment methods
* Insurance providers
* Staff roles
* Permissions
* Numbering formats
* Relevant application preferences

# SEARCH

Fast search is critical.

Provide useful search across relevant areas such as:

* Patients
* Hospital numbers
* Phone numbers
* Staff
* Medications
* Services
* Laboratory tests
* Imaging requests
* Invoices
* Admissions
* Prescriptions

# USER EXPERIENCE

Create a coherent professional healthcare product.

Prioritize:

* Fast navigation
* Fast patient search
* Minimal unnecessary clicks
* Clear information hierarchy
* Good forms
* Useful validation
* Searchable tables
* Filtering
* Sorting
* Pagination where appropriate
* Keyboard-friendly workflows
* Accessibility
* Responsive layouts
* Clear status indicators
* Useful empty states
* Good error messages
* Good loading states
* Confirmation for dangerous actions

Avoid interfaces that merely look impressive.

Clinical usability is more important than decorative UI.

# RESPONSIVE DESIGN

The system should function appropriately across:

* Desktop
* Laptop
* Tablet
* Mobile

Do not simply shrink desktop screens onto mobile devices.

# ACCESSIBILITY

Design with accessibility in mind.

Important information should not rely only on color.

Forms, navigation, errors, alerts, and interactive elements should be usable by people with different accessibility needs.

# PERFORMANCE

Hospital staff should not have to wait unnecessarily for common tasks.

Operations such as:

* Patient search
* Opening patient records
* Viewing queues
* Recording vitals
* Writing consultations
* Dispensing medication
* Entering results
* Receiving payments

should feel responsive under realistic usage.

# OPEN-SOURCE READINESS

Treat this as a project that may eventually have external users and contributors.

The repository should become suitable for public release.

Include appropriate:

* Project documentation
* Setup instructions
* Development instructions
* Environment configuration guidance
* Architecture documentation
* Contribution guidance
* Testing instructions
* Database migration guidance
* API documentation where appropriate
* Demo data
* Security reporting instructions
* Release/versioning practices
* Upgrade guidance
* Licensing

Never include:

* Real patient data
* Production secrets
* Credentials
* Private keys
* Sensitive environment values

in the repository.

# DEMO ENVIRONMENT

Provide high-quality fictional data demonstrating realistic workflows.

Someone evaluating the software should be able to explore:

* Patients
* Appointments
* Consultations
* Admissions
* Lab results
* Pharmacy
* Inventory
* Billing
* Insurance
* Staff
* Reports

without manually building the hospital from scratch.

# CLINICAL SAFETY

Do not treat healthcare workflows as ordinary business forms.

Where the software could contribute to patient harm, favor:

* Clear information
* Confirmation where appropriate
* Traceability
* Safe defaults
* Appropriate warnings
* Preserved clinical history

Do not make the system pretend to make medical decisions that should belong to qualified professionals.

# TESTING

Important functionality should have meaningful automated testing.

Give particular attention to:

* Authentication
* Authorization
* Tenant isolation
* Patient records
* Clinical records
* Clinical history/versioning
* Prescriptions
* Medication dispensing
* Medication administration
* Laboratory results
* Admissions
* Bed management
* Billing
* Payments
* Refunds
* Inventory movements
* Audit logging
* Permission boundaries

Test failure scenarios and unauthorized actions, not only happy paths.

# END-TO-END WORKFLOWS

Do not consider modules complete merely because their individual screens function.

Connected workflows matter.

The product should eventually support realistic flows such as:

Patient registration
→ appointment/check-in
→ triage/vitals
→ consultation
→ investigation request
→ sample collection
→ laboratory result
→ clinician review
→ prescription
→ pharmacy dispensing
→ billing
→ payment
→ visit completion
→ patient history.

Another example:

Emergency arrival
→ triage
→ emergency assessment
→ investigations/treatment
→ admission
→ ward
→ bed allocation
→ inpatient care
→ medication administration
→ investigations
→ discharge planning
→ discharge summary
→ final billing
→ discharge.

Another example:

Doctor prescription
→ pharmacy receives prescription
→ pharmacist reviews
→ medication dispensed
→ inventory updated
→ charge recorded where applicable
→ dispensing appears in patient history
→ audit trail recorded.

Individual modules should behave as parts of one hospital system.

# ARCHITECTURAL QUALITY

Choose architecture based on the actual needs of this product.

Avoid both:

* Under-engineering that creates an unmaintainable application
* Unnecessary complexity introduced simply because a pattern is fashionable

Document significant architectural decisions and their rationale.

The product should be capable of evolving for years without requiring a complete rewrite every time another hospital module is added.

# DOCUMENTATION OF DECISIONS

When making significant technical or product decisions, document enough reasoning that future contributors can understand why they were made.

Do not repeatedly ask me to choose between equally reasonable technical alternatives.

Make the decision.

# DEVELOPMENT APPROACH

Build incrementally while maintaining architectural coherence.

Understand how major workflows connect before implementing them.

Avoid creating dozens of disconnected modules that happen to share the same navigation.

It is acceptable to refactor earlier work when doing so materially improves the architecture.

Do not create fake functionality just to make the application appear finished.

Do not use placeholder implementations for important workflows and then present them as complete.

# SCOPE CONTROL

This is a Hospital Management System.

Do not unnecessarily turn it into:

* A complete banking platform
* Full enterprise ERP
* Payroll suite
* Social network
* Generic CRM
* Full government health infrastructure

Build adjacent capabilities only where they meaningfully support hospital operations.

# DEFINITION OF DONE

The eventual product should be capable of supporting realistic hospital operations from patient arrival through completion of care.

A mature version should satisfy the following:

1. A developer can clone the repository and understand how to run it.

2. A contributor can understand the project structure and architecture.

3. A hospital can evaluate it using realistic fictional/demo data.

4. Different staff roles have appropriate workflows.

5. Patient information is properly protected.

6. Clinical information maintains reliable history.

7. Important actions are auditable.

8. Medication workflows are traceable.

9. Laboratory workflows operate end-to-end.

10. Admissions and beds are properly managed.

11. Financial activity is traceable and internally consistent.

12. Inventory movements are traceable.

13. Permissions prevent inappropriate access.

14. Multiple facilities can eventually operate without compromising data isolation.

15. The system can evolve toward healthcare interoperability standards.

16. Deployment and recovery are properly documented.

17. The project is credible as a serious open-source Hospital Management System rather than a demonstration application.

# YOUR ROLE

Take full ownership of this project.

Understand the entire specification before making major structural decisions.

Make the architectural, engineering, UX, security, data-model, testing, and organizational decisions you believe best serve the product.

Do not require me to micromanage implementation decisions.

Do not ask me which framework, database, library, architecture pattern, component library, API style, folder structure, deployment strategy, or similar engineering option you should choose when you can reasonably decide yourself.

Document important decisions and proceed.

Do not stop after producing:

* A roadmap
* Architecture document
* Database design
* Recommendations
* Project plan
* TODO list
* Wireframes

Those are supporting artifacts, not the final objective.

The objective is to build the actual working Hospital Management System.

Establish whatever internal roadmap and architecture you need, then begin implementation and continue incrementally through the product.

Regularly inspect the existing system before making further changes so that later work remains consistent with earlier work.

Do not abandon partially completed workflows simply to start new modules.

Prefer completing meaningful vertical hospital workflows over producing large numbers of disconnected screens.

When something is unspecified but a competent engineering team could reasonably decide it, make the decision yourself and continue.

Only ask me a question when a genuine product-level ambiguity prevents responsible progress and there is no reasonable assumption you can make.

Treat this as a long-term software product that may eventually be deployed in real hospitals and maintained by an open-source community.

Build accordingly.
