import type {
  ProviderRef,
  Catalog,
  CatalogConnection,
  CatalogModel,
  CatalogProfile,
  CatalogService,
  ConnectionTarget,
  ProviderOption,
  ServiceName,
  TaskChoiceMode,
} from "./model-catalog-types";
export type { ProviderRef, Discovery } from "./model-catalog-types";

export type ProviderSource = {
  id: string;
  ref: ProviderRef;
  name: string;
  provider: string;
  source: CatalogConnection | CatalogProfile;
  service?: ServiceName;
};
export type RegistryEdit = {
  kind: "provider" | "model" | "default" | "task_choice";
  task?: {
    /**
     * Which choice this edit is. Absent means the global task model; otherwise
     * a `TaskKind` from the settings payload, and `"global"` clears that task's
     * own model so it follows the global one again.
     */
    task_kind?: string;
    mode?: TaskChoiceMode | "global";
    selection?: CatalogService["selection"];
    active_profile_id?: string | null;
    active_model_id?: string | null;
  };
  ref?: ProviderRef;
  fields?: Record<string, unknown>;
  service?: ServiceName;
  profile_id?: string;
  model_id?: string;
  model?: CatalogModel;
  config?: Partial<CatalogProfile>;
  delete?: boolean;
};
export const REGISTRY_SERVICES: ServiceName[] = [
  "llm",
  "task",
  "embedding",
  "search",
];
export const SERVICE_TITLES: Record<ServiceName, string> = {
  llm: "Language models",
  task: "Task model",
  embedding: "Embedding models",
  search: "Search",
};
export function providerIdentity(ref: ProviderRef): string {
  return ref.connection_id
    ? `connection:${ref.connection_id}`
    : `${ref.service}:${ref.profile_id}`;
}
export function providerRegistry(catalog: Catalog): ProviderSource[] {
  const result: ProviderSource[] = (catalog.connections ?? []).map(
    (source) => ({
      id: `connection:${source.id}`,
      ref: { connection_id: source.id },
      name: source.name,
      provider: source.provider,
      source,
    }),
  );
  for (const service of REGISTRY_SERVICES)
    for (const source of catalog.services[service].profiles) {
      if (
        source.provider_ref ||
        (source.connection_id &&
          result.some((p) => p.ref.connection_id === source.connection_id))
      )
        continue;
      result.push({
        id: `${service}:${source.id}`,
        ref: { service, profile_id: source.id },
        name: source.name,
        provider: source.binding || source.provider || "custom",
        source,
        service,
      });
    }
  return result;
}
export function modelProviderRef(
  service: ServiceName,
  profile: CatalogProfile,
  model?: CatalogModel | null,
): ProviderRef {
  return (
    model?.provider_ref ||
    profile.provider_ref ||
    (profile.connection_id
      ? { connection_id: profile.connection_id }
      : { service, profile_id: profile.id })
  );
}
export function modelProvider(
  catalog: Catalog,
  service: ServiceName,
  profile: CatalogProfile,
  model?: CatalogModel | null,
): ProviderSource | undefined {
  const id = providerIdentity(modelProviderRef(service, profile, model));
  return providerRegistry(catalog).find((p) => p.id === id);
}
export type RegistryModelRow = {
  key: string;
  service: ServiceName;
  profile: CatalogProfile;
  model: CatalogModel | null;
};
export function flattenModels(
  catalog: Catalog,
  services: ServiceName[],
): RegistryModelRow[] {
  const result: RegistryModelRow[] = [];
  for (const service of services)
    for (const profile of catalog.services[service].profiles) {
      if (profile.provider_only) continue;
      if (service === "search")
        result.push({
          key: `${service}:${profile.id}`,
          service,
          profile,
          model: null,
        });
      else
        for (const model of profile.models)
          result.push({
            key: `${service}:${profile.id}:${model.id}`,
            service,
            profile,
            model,
          });
    }
  return result;
}
export function providerUsage(
  catalog: Catalog,
  source: ProviderSource,
): number {
  return flattenModels(catalog, REGISTRY_SERVICES).filter(
    (item) =>
      providerIdentity(
        modelProviderRef(item.service, item.profile, item.model),
      ) === source.id,
  ).length;
}
export function providerAdapter(
  source: ProviderSource,
  service: ServiceName,
  targets: ConnectionTarget[],
  providers: Record<ServiceName, ProviderOption[]>,
) {
  const target = targets.find((t) => t.provider === source.provider)?.services[
    service === "task" ? "llm" : service
  ];
  const exact = providers[service]?.find((p) => p.value === source.provider);
  // `custom` is the generic OpenAI-compatible binding; every service but search
  // has one, so an unrecognized vendor still resolves through it. Search has no
  // generic adapter, so it keeps the vendor's own name and gets rejected by name
  // rather than masquerading as an OpenAI-compatible search engine.
  const binding =
    target?.provider ||
    exact?.value ||
    (service === "llm" ||
    service === "task" ||
    service === "search" ||
    source.service === service
      ? source.provider
      : "custom");
  return {
    ...source.ref,
    binding,
    default_base_url: target?.base_url || exact?.base_url || "",
  };
}
export function providerProbeInput(source: ProviderSource, fallbackUrl = "") {
  const s = source.source;
  return {
    ...source.ref,
    binding: source.provider,
    base_url: s.base_url || fallbackUrl,
    api_key: s.api_key,
    api_version: s.api_version,
    api_format: s.api_format || "auto",
    extra_headers: s.extra_headers,
    service: source.service || (s as CatalogConnection).source_service || "llm",
  };
}
export function updateProvider(
  catalog: Catalog,
  ref: ProviderRef,
  field: string,
  value: unknown,
): void {
  const source = providerRegistry(catalog).find(
    (p) => p.id === providerIdentity(ref),
  )?.source;
  if (!source) return;
  Object.assign(source, { [field]: value });
  if (!["name", "discovery"].includes(field)) delete source.discovery;
}

/** Three-way, entity-scoped reconciliation: edits made while a save was in
 * flight and unsaved edits to other models/providers are not replaced by its response. */
export function reconcileRegistrySave(
  current: Catalog,
  submitted: Catalog,
  live: Catalog,
  edit: RegistryEdit,
): Catalog {
  const next = structuredClone(current);
  const same = (a: unknown, b: unknown) =>
    JSON.stringify(a) === JSON.stringify(b);
  if (edit.kind === "task_choice") {
    // `overrides` rides along: a per-task pin is not visible in any of the four
    // pointer fields, so without it the row would snap back to whatever the
    // screen still held until the next full settings load.
    for (const field of [
      "mode",
      "selection",
      "active_profile_id",
      "active_model_id",
      "overrides",
    ] as const) {
      if (!same(next.services.task[field], submitted.services.task[field]))
        continue;
      const applied = live.services.task[field];
      // The whole key disappears when the last pin is cleared; copying the
      // `undefined` instead would leave a key that no longer exists upstream.
      if (applied === undefined) Reflect.deleteProperty(next.services.task, field);
      else Reflect.set(next.services.task, field, structuredClone(applied));
    }
  } else if (edit.kind === "provider" && edit.ref) {
    const id = providerIdentity(edit.ref);
    const before = providerRegistry(submitted).find((p) => p.id === id)?.source;
    const now = providerRegistry(next).find((p) => p.id === id)?.source;
    const saved = providerRegistry(live).find((p) => p.id === id)?.source;
    if (now && before && saved && same(now, before)) {
      // Untouched since it was sent: take the saved copy whole, so fields the
      // server fills in do not leave the item looking unsaved.
      replaceProvider(next, edit.ref, structuredClone(saved));
    } else if (now && before && saved) {
      for (const key of Object.keys(edit.fields ?? {}))
        if (same(Reflect.get(now, key), Reflect.get(before, key)))
          Reflect.set(now, key, structuredClone(Reflect.get(saved, key)));
    } else if (now && !saved && edit.delete) {
      if (edit.ref.connection_id)
        next.connections = next.connections?.filter(
          (c) => c.id !== edit.ref!.connection_id,
        );
      else if (edit.ref.service)
        next.services[edit.ref.service].profiles = next.services[
          edit.ref.service
        ].profiles.filter((p) => p.id !== edit.ref!.profile_id);
    }
  } else if (edit.service) {
    const service = edit.service;
    const bucket = next.services[service];
    const before = submitted.services[service].profiles.find(
      (p) => p.id === edit.profile_id,
    );
    const now = bucket.profiles.find((p) => p.id === edit.profile_id);
    const saved = live.services[service].profiles.find(
      (p) => p.id === edit.profile_id,
    );
    if (now && before && edit.kind === "model") {
      if (service === "search") {
        if (same(now, before))
          bucket.profiles = saved
            ? bucket.profiles.map((p) => (p === now ? structuredClone(saved) : p))
            : bucket.profiles.filter((p) => p.id !== now.id);
      } else {
        const id = edit.model_id || edit.model?.id;
        const previousModel = before.models.find((m) => m.id === id);
        const currentModel = now.models.find((m) => m.id === id);
        const savedModel = saved?.models.find((m) => m.id === id);
        if (same(currentModel, previousModel)) {
          now.models = now.models.filter((m) => m.id !== id);
          if (savedModel) {
            const index = before.models.findIndex((m) => m.id === id);
            now.models.splice(
              Math.max(index, 0),
              0,
              structuredClone(savedModel),
            );
          }
          if (!saved && now.models.length === 0)
            bucket.profiles = bucket.profiles.filter((p) => p.id !== now.id);
        }
        // A model saved into a new profile: the server writes the profile's own
        // fields, so adopt the ones nobody has edited since.
        if (saved)
          for (const key of new Set([...Object.keys(before), ...Object.keys(saved)])) {
            if (key === "models" || !same(Reflect.get(now, key), Reflect.get(before, key)))
              continue;
            const value = Reflect.get(saved, key);
            if (value === undefined) Reflect.deleteProperty(now, key);
            else Reflect.set(now, key, structuredClone(value));
          }
      }
    }
    if (
      same(
        [bucket.active_profile_id, bucket.active_model_id],
        [
          submitted.services[service].active_profile_id,
          submitted.services[service].active_model_id,
        ],
      )
    ) {
      bucket.active_profile_id = live.services[service].active_profile_id;
      bucket.active_model_id = live.services[service].active_model_id;
      if (service === "task") bucket.mode = live.services.task.mode;
    }
  }
  return next;
}

function replaceProvider(
  catalog: Catalog,
  ref: ProviderRef,
  value: CatalogConnection | CatalogProfile | undefined,
): void {
  if (ref.connection_id) {
    const items = catalog.connections ?? [];
    const index = items.findIndex((c) => c.id === ref.connection_id);
    if (index >= 0 && value) items[index] = value as CatalogConnection;
    else if (index >= 0) items.splice(index, 1);
    else if (value) items.push(value as CatalogConnection);
    catalog.connections = items;
  } else if (ref.service) {
    const bucket = catalog.services[ref.service];
    const index = bucket.profiles.findIndex((p) => p.id === ref.profile_id);
    if (index >= 0 && value) bucket.profiles[index] = value as CatalogProfile;
    else if (index >= 0) bucket.profiles.splice(index, 1);
    else if (value) bucket.profiles.push(value as CatalogProfile);
  }
}

/** Put one provider back to its saved state; one never saved goes away. */
export function revertProvider(catalog: Catalog, live: Catalog, ref: ProviderRef): void {
  const saved = providerRegistry(live).find((p) => p.id === providerIdentity(ref))?.source;
  replaceProvider(catalog, ref, saved && structuredClone(saved));
}

/** Put one model (or search configuration) back to its saved state. */
export function revertModel(
  catalog: Catalog,
  live: Catalog,
  service: ServiceName,
  profileId: string,
  modelId?: string,
): void {
  const bucket = catalog.services[service];
  const saved = live.services[service].profiles.find((p) => p.id === profileId);
  const index = bucket.profiles.findIndex((p) => p.id === profileId);
  if (index < 0) return;
  if (service === "search" || !saved) {
    if (saved) bucket.profiles[index] = structuredClone(saved);
    else bucket.profiles.splice(index, 1);
    return;
  }
  const profile = bucket.profiles[index];
  const savedModel = saved.models.find((m) => m.id === modelId);
  const at = profile.models.findIndex((m) => m.id === modelId);
  if (at >= 0 && savedModel) profile.models[at] = structuredClone(savedModel);
  else if (at >= 0) profile.models.splice(at, 1);
}
