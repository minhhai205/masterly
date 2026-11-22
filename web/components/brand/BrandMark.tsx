import Link from "next/link";

/** The Masterly mark: a rounded tile with an "M" and, unless compact, the name. */
export function BrandMark({
  compact = false,
  href = "/",
}: {
  compact?: boolean;
  href?: string;
}) {
  return (
    <Link href={href} prefetch={false} className="group flex items-center gap-2">
      <span
        aria-hidden
        className="flex h-[22px] w-[22px] items-center justify-center rounded-md bg-[var(--primary)] text-[13px] font-semibold leading-none text-[var(--primary-foreground)] transition-transform duration-200 group-hover:scale-105"
      >
        M
      </span>
      {compact ? (
        <span className="sr-only">Masterly</span>
      ) : (
        <span className="font-serif text-[17px] font-semibold tracking-tight text-[var(--foreground)]">
          Masterly
        </span>
      )}
    </Link>
  );
}
