import { Bot } from "lucide-react";

/**
 * Vendor logos for LLM/embedding providers, keyed by binding name
 * (see masterly/services/provider_registry.py). SVGs are vendored from
 * @lobehub/icons-static-svg (MIT) into /public/provider-icons.
 *
 * `mono` icons are solid-fill brand marks that render black as <img>;
 * they get `dark:invert` so they stay visible on dark backgrounds.
 * Unknown/custom bindings fall back to the generic Bot icon.
 */
const PROVIDER_ICONS: Record<string, { file: string; mono?: boolean }> = {
  openai: { file: "openai.svg", mono: true },
  openai_codex: { file: "openai.svg", mono: true },
  anthropic: { file: "anthropic.svg", mono: true },
  custom_anthropic: { file: "anthropic.svg", mono: true },
  azure_openai: { file: "azure-color.svg" },
  openrouter: { file: "openrouter.svg", mono: true },
  deepseek: { file: "deepseek-color.svg" },
  gemini: { file: "gemini-color.svg" },
  google: { file: "gemini-color.svg" },
  ollama: { file: "ollama.svg", mono: true },
  groq: { file: "groq.svg", mono: true },
  cohere: { file: "cohere-color.svg" },
  jina: { file: "jina.svg", mono: true },
  // Search providers. A search provider with no vendored logo falls back to
  // the generic Bot mark rather than borrowing an unrelated brand's.
  tavily: { file: "tavily-color.svg" },
  brave: { file: "brave.svg" },
  duckduckgo: { file: "duckduckgo.svg" },
  searxng: { file: "searxng.svg" },
};

export default function ProviderIcon({
  provider,
  size = 13,
  className = "",
}: {
  provider?: string | null;
  size?: number;
  className?: string;
}) {
  const spec = provider
    ? PROVIDER_ICONS[provider.trim().toLowerCase()]
    : undefined;
  if (!spec) {
    return (
      <Bot
        size={size}
        strokeWidth={1.7}
        className={`shrink-0 ${className}`.trim()}
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/provider-icons/${spec.file}`}
      alt=""
      aria-hidden
      width={size}
      height={size}
      draggable={false}
      className={`shrink-0 select-none ${spec.mono ? "dark:invert" : ""} ${className}`.trim()}
    />
  );
}
