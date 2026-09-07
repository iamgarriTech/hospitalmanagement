import Image from 'next/image'

/** Product identity; organization and facility names belong to the workspace. */
export function BrandLogo({
  variant = 'full',
  className = '',
}: {
  variant?: 'full' | 'light' | 'icon'
  className?: string
}) {
  const iconOnly = variant === 'icon'
  const src = iconOnly
    ? '/brand/vitacore-icon.png'
    : `/brand/vitacore-horizontal${variant === 'light' ? '-light' : ''}.png`

  return (
    <Image
      src={src}
      alt="VitaCore"
      width={iconOnly ? 512 : 1088}
      height={iconOnly ? 512 : 256}
      unoptimized
      loading="eager"
      className={`block shrink-0 object-contain ${iconOnly ? 'size-9' : 'h-auto w-[170px]'} ${className}`}
    />
  )
}
