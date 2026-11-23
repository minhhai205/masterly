"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";
import { setModelReasoningEffort } from "@/lib/reasoning-effort";
import {
  detachProfileConnection,
  modelTestKey,
  modelTestFingerprint,
  type ModelTestState,
} from "@/lib/model-settings";
import {
  reconcileRegistrySave,
  type RegistryEdit,
} from "@/lib/provider-registry";
import { browserStorage } from "@/shared/storage";

import {
  CONNECTABLE_SERVICES,
  type ProviderRef,
  type Discovery,
  type ServiceName,
  type ModelCapabilities,
  type ModelCapabilityKey,
  type ApiFormat,
  type CatalogModel,
  type LlmContextWindowDetection,
  type CatalogProfile,
  type CatalogService,
  type CatalogConnection,
  type ConnectionTargetService,
  type ConnectionTarget,
  type Catalog,
  type ProviderOption,
  type CatalogTaskOverride,
  type TaskKindInfo,
} from "@/lib/model-catalog-types";
export { CONNECTABLE_SERVICES } from "@/lib/model-catalog-types";
export type {
  ProviderRef,
  Discovery,
  ServiceName,
  ModelCapabilities,
  ModelCapabilityKey,
  ApiFormat,
  CatalogModel,
  LlmContextWindowDetection,
  CatalogProfile,
  CatalogService,
  CatalogTaskOverride,
  TaskKindInfo,
  CatalogConnection,
  ConnectionTargetService,
  ConnectionTarget,
  Catalog,
  ProviderOption,
} from "@/lib/model-catalog-types";

// ─── Domain types ─────────────────────────────────────────────────────────

export type EmbeddingCapabilities = {
  detected_dim?: number;
  default_dim?: number;
  supported_dimensions?: number[];
  supports_variable_dimensions?: boolean;
  model_known?: boolean;
  active_dim?: number;
  active_dim_source?: string;
};

export type DiagnosticsResult = {
  state: "success" | "failed";
  message: string;
  profileId: string | null;
  modelId: string | null;
};

export type ServiceReadiness =
  "not_configured" | "untested" | "passed" | "failed";

type SettingsPayload = {
  catalog?: Catalog;
  providers?: Record<ServiceName, ProviderOption[]>;
  connection_targets?: ConnectionTarget[];
  task_kinds?: TaskKindInfo[];
};

const DIAGNOSTICS_RESULTS_KEY = "masterly.settings.diagnosticsResults.v1";

// ─── Helpers ───────────────────────────────────────────────────────────────

export function cloneCatalog(catalog: Catalog): Catalog {
  return JSON.parse(JSON.stringify(catalog)) as Catalog;
}

export function defaultCatalog(): Catalog {
  return {
    version: 1,
    connections: [],
    services: {
      llm: { active_profile_id: null, active_model_id: null, profiles: [] },
      task: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      embedding: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      search: { active_profile_id: null, profiles: [] },
    },
  };
}

export function getActiveProfile(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogProfile | null {
  const service = catalog.services[serviceName];
  return (
    service.profiles.find(
      (profile) => profile.id === service.active_profile_id,
    ) ??
    service.profiles[0] ??
    null
  );
}

export function getActiveModel(
  catalog: Catalog,
  serviceName: ServiceName,
): CatalogModel | null {
  if (serviceName === "search") return null;
  const service = catalog.services[serviceName];
  const profile = getActiveProfile(catalog, serviceName);
  if (!profile) return null;
  return (
    profile.models.find((model) => model.id === service.active_model_id) ??
    profile.models[0] ??
    null
  );
}

export function serviceConfigured(
  catalog: Catalog,
  serviceName: ServiceName,
): boolean {
  return serviceName === "search"
    ? Boolean(getActiveProfile(catalog, serviceName)?.provider)
    : Boolean(getActiveModel(catalog, serviceName)?.model);
}

export function currentDiagnosticsResult(
  catalog: Catalog,
  serviceName: ServiceName,
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>,
): DiagnosticsResult | null {
  const service = catalog.services[serviceName];
  const diagnostics = diagnosticsResults[serviceName];
  if (!diagnostics) return null;
  const profileId = service.active_profile_id ?? null;
  const modelId =
    serviceName === "search" ? null : (service.active_model_id ?? null);
  return diagnostics.profileId === profileId && diagnostics.modelId === modelId
    ? diagnostics
    : null;
}

export function serviceReadiness(
  catalog: Catalog,
  serviceName: ServiceName,
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>,
): ServiceReadiness {
  if (!serviceConfigured(catalog, serviceName)) return "not_configured";
  const diagnostics = currentDiagnosticsResult(
    catalog,
    serviceName,
    diagnosticsResults,
  );
  if (diagnostics?.state === "failed") return "failed";
  if (diagnostics?.state === "success") return "passed";
  return "untested";
}

function nextModelName(models: CatalogModel[]): string {
  const prefix = "Model ";
  const used = new Set(models.map((model) => model.name.trim()));
  let index = models.length + 1;
  while (used.has(`${prefix}${index}`)) {
    index += 1;
  }
  return `${prefix}${index}`;
}

function readStoredDiagnosticsResults(): Partial<
  Record<ServiceName, DiagnosticsResult>
> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(
      browserStorage.readRaw("session", DIAGNOSTICS_RESULTS_KEY) || "{}",
    ) as Partial<Record<ServiceName, DiagnosticsResult>>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

// ─── Context ───────────────────────────────────────────────────────────────

export type SettingsContextValue = {
  // State
  /** What is saved and running. */
  catalog: Catalog;
  /** The editable copy on screen; an item differs from `catalog` until it is saved. */
  draft: Catalog;
  providers: Record<ServiceName, ProviderOption[]>;
  /** True for the administrator; false for a learner, who never sees the catalog. */
  catalogEditable: boolean | null;
  settingsLoading: boolean;
  settingsError: string | null;
  reloadSettings: () => Promise<void>;
  hasUnsavedChanges: boolean;
  toast: string;
  setToast: (value: string) => void;

  // Catalog mutation
  mutateCatalog: (mutator: (next: Catalog) => void) => void;
  addProfile: (service: ServiceName) => void;
  /** Omitting the id targets whatever is in use — the historical meaning. */
  removeActiveProfile: (service: ServiceName, profileId?: string) => void;
  addModel: (service: ServiceName, profileId?: string) => void;
  removeActiveModel: (
    service: ServiceName,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateProfileField: (
    service: ServiceName,
    field: keyof CatalogProfile,
    value: string,
    profileId?: string,
  ) => void;
  updateModelField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateModelBoolField: (
    service: ServiceName,
    field: keyof CatalogModel,
    value: boolean,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateContextWindowField: (
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  updateReasoningEffort: (
    value: string,
    profileId?: string,
    modelId?: string,
  ) => void;
  /** `null` clears the override so the built-in tables decide again. */
  updateModelCapability: (
    service: ServiceName,
    key: ModelCapabilityKey,
    value: boolean | null,
    profileId?: string,
    modelId?: string,
  ) => void;

  // Connections + task models
  connectionTargets: ConnectionTarget[];
  /** The calls Masterly makes on its own, in the order the backend lists them. */
  taskKinds: TaskKindInfo[];
  connectionTarget: (provider: string) => ConnectionTarget | null;
  addConnection: (input: {
    provider: string;
    name: string;
    api_key: string;
    base_url: string;
  }) => CatalogConnection;
  updateConnectionField: (
    id: string,
    field: keyof CatalogConnection,
    value: string,
  ) => void;
  removeConnection: (id: string) => void;
  unlinkProfile: (service: ServiceName, profileId: string) => void;
  linkConnectionToServices: (
    connection: Pick<
      CatalogConnection,
      "id" | "provider" | "name" | "api_key" | "base_url"
    >,
    requests: { service: ServiceName; model: string }[],
  ) => { created: ServiceName[]; activated: ServiceName[] };
  llmContextDetection: LlmContextWindowDetection | null;
  applyDetectedContextWindow: () => void;

  // Saving: each edit names one item and is live as soon as it returns.
  applying: boolean;
  saveRegistry: (edit: RegistryEdit) => Promise<boolean>;

  // Diagnostics
  modelTests: Record<string, ModelTestState>;
  logs: string;
  testRunning: ServiceName | null;
  diagnosticsResults: Partial<Record<ServiceName, DiagnosticsResult>>;
  embeddingCapabilities: EmbeddingCapabilities | null;
  runDetailedTest: (
    service: ServiceName,
    selection?: { profileId: string; modelId?: string },
  ) => Promise<void>;

  // Helpers
  embeddingDefaultDim: (binding?: string) => string;
};

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) {
    throw new Error("useSettings must be used inside <SettingsProvider>");
  }
  return ctx;
}

// ─── Provider ──────────────────────────────────────────────────────────────

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();

  const [catalog, setCatalog] = useState<Catalog>(defaultCatalog());
  const [draft, setDraft] = useState<Catalog>(defaultCatalog());
  const [catalogEditable, setCatalogEditable] = useState<boolean | null>(null);
  const [providers, setProviders] = useState<
    Record<ServiceName, ProviderOption[]>
  >({
    llm: [],
    task: [],
    embedding: [],
    search: [],
  });
  const [connectionTargets, setConnectionTargets] = useState<
    ConnectionTarget[]
  >([]);
  const [taskKinds, setTaskKinds] = useState<TaskKindInfo[]>([]);
  const [toast, setToast] = useState("");
  const [applying, setApplying] = useState(false);
  // Empty string is the "no diagnostics yet" sentinel; the editor renders
  // a localized placeholder when logs is falsy. Don't seed an English
  // literal here — older code did, then read it back via .startsWith.
  const [logs, setLogs] = useState<string>("");
  const [modelTests, setModelTests] = useState<Record<string, ModelTestState>>(
    {},
  );
  const testBusyRef = useRef(false);
  const [testRunning, setTestRunning] = useState<ServiceName | null>(null);
  const [diagnosticsResults, setDiagnosticsResults] = useState<
    Partial<Record<ServiceName, DiagnosticsResult>>
  >(() => readStoredDiagnosticsResults());
  const [llmContextDetection, setLlmContextDetection] =
    useState<LlmContextWindowDetection | null>(null);
  const [embeddingCapabilities, setEmbeddingCapabilities] =
    useState<EmbeddingCapabilities | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);

  // Single load step. Kept separate from the mount effect so a "Retry" action
  // can re-run it without remounting the provider.
  const loadSettings = useCallback(async () => {
    setSettingsError(null);
    try {
      const settingsResponse = await apiFetch(apiUrl("/api/settings"));
      if (!settingsResponse.ok) {
        throw new Error(
          `Settings fetch failed: HTTP ${settingsResponse.status}`,
        );
      }
      const payload = (await settingsResponse.json()) as SettingsPayload;
      if (!payload.catalog) {
        // A learner: the model catalog belongs to the administrator.
        setCatalogEditable(false);
        return;
      }
      setCatalog(payload.catalog);
      setDraft(cloneCatalog(payload.catalog));
      setCatalogEditable(true);
      if (payload.providers) setProviders(payload.providers);
      if (payload.connection_targets)
        setConnectionTargets(payload.connection_targets);
      if (payload.task_kinds) setTaskKinds(payload.task_kinds);
    } catch (err) {
      console.error("Failed to load settings:", err);
      setSettingsError(err instanceof Error ? err.message : String(err));
      // Resolve the loading gate so the page can render the error UI instead
      // of staying in an infinite skeleton state.
      setCatalogEditable((current) => (current === null ? false : current));
    }
  }, []);

  // Load once on mount; navigations between settings pages share this state
  // through the layout-level provider. `reloadSettings` is the deliberate way
  // to re-read.
  const loadedOnce = useRef(false);
  useEffect(() => {
    if (!loadedOnce.current) {
      loadedOnce.current = true;
      loadSettings();
    }
  }, [loadSettings]);

  // Close a running model test's event stream when Settings unmounts.
  useEffect(() => () => eventSourceRef.current?.close(), []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    try {
      browserStorage.writeRaw(
        "session",
        DIAGNOSTICS_RESULTS_KEY,
        JSON.stringify(diagnosticsResults),
      );
    } catch {
      // Session storage is an enhancement for cross-route feedback only.
    }
  }, [diagnosticsResults]);

  // ── Catalog mutators ────────────────────────────────────────────────────
  const mutateCatalog = useCallback((mutator: (next: Catalog) => void) => {
    setDraft((current) => {
      const next = cloneCatalog(current);
      mutator(next);
      return next;
    });
  }, []);

  const embeddingDefaultDim = useCallback(
    (binding?: string) => {
      const match = (providers.embedding || []).find(
        (p) => p.value === (binding || "openai"),
      );
      return match?.default_dim || "3072";
    },
    [providers.embedding],
  );

  const addProfile = useCallback(
    (service: ServiceName) => {
      mutateCatalog((next) => {
        const target = next.services[service];
        const profileId = `${service}-profile-${Date.now()}`;
        const defaultBinding = service === "search" ? undefined : "openai";
        const defaultProvider = service === "search" ? "brave" : undefined;
        const providerKey =
          service === "search" ? defaultProvider : defaultBinding;
        const providerOption = (providers[service] || []).find(
          (p) => p.value === providerKey,
        );
        const providerLabel =
          providerOption?.label ?? providerKey ?? "New Profile";
        const profile: CatalogProfile = {
          id: profileId,
          name: providerLabel,
          binding: defaultBinding,
          provider: defaultProvider,
          base_url: providerOption?.base_url ?? "",
          api_key: "",
          api_version: "",
          extra_headers: service === "search" ? undefined : {},
          wire_api: service === "llm" ? "auto" : undefined,
          api_format:
            service === "llm" || service === "task" ? "auto" : undefined,
          proxy: service === "search" ? "" : undefined,
          models: [],
        };
        if (service !== "search") {
          const modelId = `${service}-model-${Date.now()}`;
          profile.models.push({
            id: modelId,
            name: nextModelName([]),
            model: "",
            ...(service === "embedding"
              ? {
                  dimension: embeddingDefaultDim(),
                  send_dimensions: true,
                }
              : {}),
          });
          if (!target.active_profile_id) target.active_model_id = modelId;
        }
        target.profiles.push(profile);
        if (!target.active_profile_id) target.active_profile_id = profileId;
      });
    },
    [embeddingDefaultDim, mutateCatalog, providers],
  );

  const removeActiveProfile = useCallback(
    (service: ServiceName, profileId?: string) => {
      mutateCatalog((next) => {
        const target = next.services[service];
        const doomed = profileId ?? target.active_profile_id;
        target.profiles = target.profiles.filter(
          (profile) => profile.id !== doomed,
        );
        // Deleting a profile that was not in use leaves the selection alone.
        if (target.active_profile_id === doomed) {
          target.active_profile_id = target.profiles[0]?.id ?? null;
          if (service !== "search") {
            target.active_model_id =
              target.profiles[0]?.models?.[0]?.id ?? null;
          }
        }
      });
    },
    [mutateCatalog],
  );

  const addModel = useCallback(
    (service: ServiceName, profileId?: string) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile = profileId
          ? (target.profiles.find((item) => item.id === profileId) ?? null)
          : (target.profiles.find(
              (item) => item.id === target.active_profile_id,
            ) ?? null);
        if (!profile) return;
        const modelId = `${service}-model-${Date.now()}`;
        profile.models.push({
          id: modelId,
          name: nextModelName(profile.models),
          model: "",
          ...(service === "embedding"
            ? {
                dimension: embeddingDefaultDim(profile.binding),
                send_dimensions: true,
              }
            : {}),
        });
        // Adding an option must not silently replace an existing selection.
        if (
          profile.id === target.active_profile_id &&
          !target.active_model_id
        ) {
          target.active_model_id = modelId;
        }
      });
    },
    [embeddingDefaultDim, mutateCatalog],
  );

  // ─── Connections ─────────────────────────────────────────────────────────
  //
  // A connection holds the credential; linking creates one ordinary profile
  // per service that points back at it. The backend mirrors the credential
  // down on save, so everything downstream keeps reading self-contained
  // profiles — nothing about how a profile resolves changes by being linked.

  const connectionTarget = useCallback(
    (provider: string) =>
      connectionTargets.find((target) => target.provider === provider) ?? null,
    [connectionTargets],
  );

  const addConnection = useCallback(
    (input: {
      provider: string;
      name: string;
      api_key: string;
      base_url: string;
    }) => {
      const connection: CatalogConnection = {
        id: `conn-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        name: input.name.trim() || input.provider,
        provider: input.provider,
        api_key: input.api_key,
        base_url: input.base_url.trim(),
        api_version: "",
        extra_headers: {},
      };
      mutateCatalog((next) => {
        next.connections = [...(next.connections ?? []), { ...connection }];
      });
      // Returned whole because the caller links services in the same click,
      // before the edit carrying it has been saved.
      return connection;
    },
    [mutateCatalog],
  );

  const updateConnectionField = useCallback(
    (id: string, field: keyof CatalogConnection, value: string) => {
      mutateCatalog((next) => {
        const connection = (next.connections ?? []).find(
          (item) => item.id === id,
        );
        if (connection) (connection as Record<string, unknown>)[field] = value;
      });
    },
    [mutateCatalog],
  );

  /**
   * Drop a connection. Profiles it fed keep the credentials already mirrored
   * into them — deleting the place a key was typed must not silently break
   * six working services.
   */
  const removeConnection = useCallback(
    (id: string) => {
      mutateCatalog((next) => {
        for (const service of CONNECTABLE_SERVICES) {
          for (const profile of next.services[service].profiles) {
            if (profile.connection_id === id)
              detachProfileConnection(next, service, profile);
          }
        }
        next.connections = (next.connections ?? []).filter(
          (item) => item.id !== id,
        );
      });
    },
    [mutateCatalog],
  );

  const unlinkProfile = useCallback(
    (service: ServiceName, profileId: string) => {
      mutateCatalog((next) => {
        const profile = next.services[service].profiles.find(
          (item) => item.id === profileId,
        );
        if (profile) detachProfileConnection(next, service, profile);
      });
    },
    [mutateCatalog],
  );

  /**
   * Create one linked profile per requested service.
   *
   * The plan — ids, which services get one, which of those become active — is
   * computed here rather than inside the catalog mutator: a mutator is a React
   * updater, so it runs during render (twice under StrictMode) and anything it
   * reports back would be both late and doubled.
   *
   * A new profile becomes the active one only for services that had none. A
   * user who already has a working LLM must not find their chat model swapped
   * out because they pasted a key for image generation, so what did and did
   * not become active is returned for the caller to say out loud.
   */
  const linkConnectionToServices = useCallback(
    (
      connection: Pick<
        CatalogConnection,
        "id" | "provider" | "name" | "api_key" | "base_url"
      >,
      requests: { service: ServiceName; model: string }[],
    ) => {
      const target = connectionTargets.find(
        (item) => item.provider === connection.provider,
      );
      const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
      const base = connection.base_url.trim().replace(/\/+$/, "");
      const plan = requests.flatMap((request, index) => {
        const spec = target?.services[request.service];
        if (!spec) return [];
        return [
          {
            service: request.service,
            spec,
            profileId: `${request.service}-profile-${stamp}${index}`,
            modelId: `${request.service}-model-${stamp}${index}`,
            model: request.model || spec.default_model || "",
            // Mirrored from the connection on save; seeded here so the screen
            // shows the same values the server will store.
            baseUrl: base
              ? request.service === "embedding"
                ? `${base}/embeddings`
                : base
              : spec.base_url,
            activate: draft.services[request.service].profiles.length === 0,
          },
        ];
      });

      mutateCatalog((next) => {
        for (const item of plan) {
          const bucket = next.services[item.service];
          bucket.profiles.push({
            id: item.profileId,
            name: connection.name,
            connection_id: connection.id,
            binding: item.spec.provider,
            base_url: item.baseUrl,
            api_key: connection.api_key,
            api_version: "",
            extra_headers: {},
            models: [
              {
                id: item.modelId,
                name: item.model || item.spec.provider,
                model: item.model,
                ...(item.service === "embedding"
                  ? {
                      dimension: item.spec.default_dim || "",
                      send_dimensions: true,
                    }
                  : {}),
              },
            ],
          });
          if (item.activate) {
            bucket.active_profile_id = item.profileId;
            bucket.active_model_id = item.modelId;
          }
        }
      });

      return {
        created: plan.map((item) => item.service),
        activated: plan
          .filter((item) => item.activate)
          .map((item) => item.service),
      };
    },
    [connectionTargets, draft, mutateCatalog],
  );

  const removeActiveModel = useCallback(
    (service: ServiceName, profileId?: string, modelId?: string) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const target = next.services[service];
        const profile = profileId
          ? (target.profiles.find((item) => item.id === profileId) ?? null)
          : (target.profiles.find(
              (item) => item.id === target.active_profile_id,
            ) ?? null);
        if (!profile) return;
        const doomed = modelId ?? target.active_model_id;
        profile.models = profile.models.filter((item) => item.id !== doomed);
        if (target.active_model_id === doomed) {
          target.active_model_id =
            profile.id === target.active_profile_id
              ? (profile.models[0]?.id ?? null)
              : target.active_model_id;
        }
      });
    },
    [mutateCatalog],
  );

  /**
   * Which profile/model an edit lands on.
   *
   * Everything here used to write to whatever was *active*, because selecting
   * a profile and putting it into use were the same act. The model pages now
   * let you open a profile without adopting it, so an edit has to name its
   * target — omitting it keeps the old meaning, so no existing caller changes.
   */
  const targetProfile = useCallback(
    (next: Catalog, service: ServiceName, profileId?: string) =>
      profileId
        ? (next.services[service].profiles.find(
            (item) => item.id === profileId,
          ) ?? null)
        : getActiveProfile(next, service),
    [],
  );

  const targetModel = useCallback(
    (
      next: Catalog,
      service: ServiceName,
      profileId?: string,
      modelId?: string,
    ) => {
      if (!profileId && !modelId) return getActiveModel(next, service);
      const profile = targetProfile(next, service, profileId);
      if (!profile) return null;
      return modelId
        ? (profile.models.find((item) => item.id === modelId) ?? null)
        : (profile.models[0] ?? null);
    },
    [targetProfile],
  );

  const updateProfileField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogProfile,
      value: string,
      profileId?: string,
    ) => {
      mutateCatalog((next) => {
        const profile = targetProfile(next, service, profileId);
        if (!profile) return;
        (profile[field] as string | undefined) = value;
      });
    },
    [mutateCatalog, targetProfile],
  );

  const updateModelField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogModel,
      value: string,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        (model[field] as string | undefined) = value;
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateModelBoolField = useCallback(
    (
      service: ServiceName,
      field: keyof CatalogModel,
      value: boolean,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        (model[field] as boolean | undefined) = value;
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateContextWindowField = useCallback(
    (value: string, profileId?: string, modelId?: string) => {
      const normalized = value.replace(/[^\d]/g, "");
      mutateCatalog((next) => {
        const model = targetModel(next, "llm", profileId, modelId);
        if (!model) return;
        if (normalized) {
          model.context_window = normalized;
          model.context_window_source = "manual";
          delete model.context_window_detected_at;
        } else {
          delete model.context_window;
          delete model.context_window_source;
          delete model.context_window_detected_at;
        }
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateReasoningEffort = useCallback(
    (value: string, profileId?: string, modelId?: string) => {
      mutateCatalog((next) => {
        const model = targetModel(next, "llm", profileId, modelId);
        if (!model) return;
        setModelReasoningEffort(model, value);
      });
    },
    [mutateCatalog, targetModel],
  );

  const updateModelCapability = useCallback(
    (
      service: ServiceName,
      key: ModelCapabilityKey,
      value: boolean | null,
      profileId?: string,
      modelId?: string,
    ) => {
      if (service === "search") return;
      mutateCatalog((next) => {
        const model = targetModel(next, service, profileId, modelId);
        if (!model) return;
        const capabilities = { ...(model.capabilities ?? {}) };
        if (value === null) delete capabilities[key];
        else capabilities[key] = value;
        if (Object.keys(capabilities).length === 0) delete model.capabilities;
        else model.capabilities = capabilities;
      });
    },
    [mutateCatalog, targetModel],
  );

  const applyDetectedContextWindow = useCallback(() => {
    if (!llmContextDetection || llmContextDetection.source === "default") return;
    mutateCatalog((next) => {
      const target = next.services.llm;
      if (
        target.active_profile_id !== llmContextDetection.profileId ||
        target.active_model_id !== llmContextDetection.modelId
      ) {
        return;
      }
      const model = getActiveModel(next, "llm");
      if (!model) return;
      model.context_window = String(llmContextDetection.contextWindow);
      model.context_window_source = llmContextDetection.source;
      if (llmContextDetection.detectedAt) {
        model.context_window_detected_at = llmContextDetection.detectedAt;
      } else {
        delete model.context_window_detected_at;
      }
    });
    setToast(t("Detected context window filled in. Save the model to keep it."));
  }, [llmContextDetection, mutateCatalog, t]);

  // ── Save ────────────────────────────────────────────────────────────────
  const saveRegistry = useCallback(
    async (edit: RegistryEdit): Promise<boolean> => {
      setApplying(true);
      try {
        const response = await apiFetch(
          apiUrl("/api/settings/apply/registry"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(edit),
          },
        );
        const payload = await response.json();
        if (!response.ok)
          throw new Error(
            typeof payload.detail === "string"
              ? payload.detail
              : `HTTP ${response.status}`,
          );
        setCatalog(payload.catalog);
        setDraft((current) =>
          reconcileRegistrySave(current, draft, payload.catalog, edit),
        );
        const normalized = reconcileRegistrySave(
          draft,
          draft,
          payload.catalog,
          edit,
        );
        setModelTests((current) => {
          const next = { ...current };
          for (const [key, result] of Object.entries(next)) {
            const [service, profileId, modelId] = JSON.parse(key) as [
              ServiceName,
              string,
              string | null,
            ];
            if (
              result.fingerprint ===
              modelTestFingerprint(draft, service, profileId, modelId)
            )
              next[key] = {
                ...result,
                fingerprint: modelTestFingerprint(
                  normalized,
                  service,
                  profileId,
                  modelId,
                ),
              };
          }
          return next;
        });
        setToast(t("Saved"));
        return true;
      } catch (error) {
        setToast(
          t("Could not save: {{message}}", {
            message: error instanceof Error ? error.message : String(error),
          }),
        );
        return false;
      } finally {
        setApplying(false);
      }
    },
    [draft, t],
  );

  // ── Diagnostics ─────────────────────────────────────────────────────────
  // Reset capability snapshot when switching embedding profile/model so a
  // stale "Detected: Xd" hint doesn't bleed across profiles.
  useEffect(() => {
    setEmbeddingCapabilities(null);
  }, [
    draft.services.embedding.active_profile_id,
    draft.services.embedding.active_model_id,
  ]);

  const llmActiveProfileId = draft.services.llm.active_profile_id;
  const llmActiveModelId = draft.services.llm.active_model_id;
  useEffect(() => {
    setLlmContextDetection((current) => {
      if (!current) return null;
      if (
        current.profileId === llmActiveProfileId &&
        current.modelId === llmActiveModelId
      ) {
        return current;
      }
      return null;
    });
  }, [llmActiveProfileId, llmActiveModelId]);

  const runDetailedTest = useCallback(
    async (
      service: ServiceName,
      selection?: { profileId: string; modelId?: string },
    ) => {
      if (!catalogEditable || testBusyRef.current) return;
      const diagnosticCatalog = cloneCatalog(draft);
      const target = diagnosticCatalog.services[service];
      const runProfileId = selection?.profileId ?? target.active_profile_id;
      const runModelId =
        service === "search"
          ? null
          : (selection?.modelId ?? target.active_model_id);
      const profile = target.profiles.find((item) => item.id === runProfileId);
      if (
        !profile ||
        (service !== "search" &&
          !profile.models.some(
            (item) => item.id === runModelId && item.model.trim(),
          ))
      )
        return;
      if (service === "task") target.mode = "profiles";
      target.active_profile_id = runProfileId;
      if (service !== "search") target.active_model_id = runModelId;
      const key = modelTestKey(service, profile.id, runModelId);
      const fingerprint = modelTestFingerprint(
        draft,
        service,
        profile.id,
        runModelId,
      );
      let finished = false;
      testBusyRef.current = true;
      setTestRunning(service);
      setLogs("");
      setModelTests((current) => ({
        ...current,
        [key]: {
          state: "running",
          fingerprint,
          logs: "",
          message: t("Testing model…"),
        },
      }));
      const update = (patch: Partial<ModelTestState>) =>
        setModelTests((current) => ({
          ...current,
          [key]: { ...current[key], ...patch },
        }));
      const finish = (state: "success" | "failed", message: string) => {
        if (finished) return;
        finished = true;
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        testBusyRef.current = false;
        setTestRunning(null);
        update({ state, message });
        setDiagnosticsResults((current) => ({
          ...current,
          [service]: {
            state,
            message,
            profileId: profile.id,
            modelId: runModelId ?? null,
          },
        }));
      };
      try {
        const response = await apiFetch(
          apiUrl(`/api/settings/tests/${service}/start`),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ catalog: diagnosticCatalog }),
          },
        );
        const payload = await response.json();
        if (!response.ok || !payload.run_id)
          throw new Error(
            typeof payload.detail === "string"
              ? payload.detail
              : t("Could not start diagnostics."),
          );
        const source = new EventSource(
          apiUrl(`/api/settings/tests/${service}/${payload.run_id}/events`),
          { withCredentials: true },
        );
        eventSourceRef.current = source;
        source.onmessage = (event) => {
          if (finished) return;
          try {
            const entry = JSON.parse(event.data);
            const line = `[${entry.type}] ${entry.message || ""}\n`;
            setLogs((current) => current + line);
            setModelTests((current) => ({
              ...current,
              [key]: {
                ...current[key],
                logs: current[key].logs + line,
                message: entry.message || current[key].message,
              },
            }));
            if (entry.type === "response" && entry.snippet)
              update({ response: entry.snippet });
            if (
              entry.type === "context_window" &&
              Number(entry.context_window) > 0
            ) {
              const context = {
                value: Number(entry.context_window),
                source: entry.source || "metadata",
                detail: entry.detail,
                detectedAt: entry.detected_at,
              };
              update({ context });
              if (service === "llm")
                setLlmContextDetection({
                  profileId: profile.id,
                  modelId: runModelId ?? null,
                  contextWindow: context.value,
                  source: context.source,
                  detail: context.detail,
                  detectedAt: context.detectedAt,
                });
            }
            if (entry.type === "capabilities") {
              update({
                dimension: entry.detected_dim,
                supportedDimensions: entry.supported_dimensions,
              });
              setEmbeddingCapabilities(entry);
            }
            // A probe never replaces the catalog or the user's in-progress edits.
            // Metadata is offered to the addressed model for explicit adoption.
            if (entry.type === "completed") finish("success", entry.message);
            if (entry.type === "failed") finish("failed", entry.message);
          } catch {
            finish("failed", t("Could not read the model test result."));
          }
        };
        source.onerror = () =>
          finish("failed", t("Diagnostics stream disconnected."));
      } catch (error) {
        finish(
          "failed",
          error instanceof Error
            ? error.message
            : t("Could not start diagnostics."),
        );
      }
    },
    [catalogEditable, draft, t],
  );

  // ── Derived ─────────────────────────────────────────────────────────────
  // Anything on screen that is not what is saved: an item edited but not saved.
  const hasUnsavedChanges = useMemo(
    () =>
      catalogEditable === true &&
      JSON.stringify(catalog) !== JSON.stringify(draft),
    [catalog, catalogEditable, draft],
  );

  // Moving between settings pages keeps unsaved edits (they live on the
  // provider), but closing or reloading the tab cannot — that is the moment
  // the work would disappear, so warn there.
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasUnsavedChanges]);

  const settingsLoading = catalogEditable === null;

  const value = useMemo<SettingsContextValue>(
    () => ({
      catalog,
      draft,
      providers,
      catalogEditable,
      settingsLoading,
      settingsError,
      reloadSettings: loadSettings,
      hasUnsavedChanges,
      toast,
      setToast,
      mutateCatalog,
      addProfile,
      removeActiveProfile,
      addModel,
      removeActiveModel,
      updateProfileField,
      updateModelField,
      updateModelBoolField,
      updateContextWindowField,
      updateReasoningEffort,
      updateModelCapability,
      connectionTargets,
      taskKinds,
      connectionTarget,
      addConnection,
      updateConnectionField,
      removeConnection,
      unlinkProfile,
      linkConnectionToServices,
      llmContextDetection,
      applyDetectedContextWindow,
      applying,
      saveRegistry,
      logs,
      testRunning,
      modelTests,
      diagnosticsResults,
      embeddingCapabilities,
      runDetailedTest,
      embeddingDefaultDim,
    }),
    [
      catalog,
      draft,
      providers,
      catalogEditable,
      settingsLoading,
      settingsError,
      loadSettings,
      hasUnsavedChanges,
      toast,
      mutateCatalog,
      addProfile,
      removeActiveProfile,
      addModel,
      removeActiveModel,
      updateProfileField,
      updateModelField,
      updateModelBoolField,
      updateContextWindowField,
      updateReasoningEffort,
      updateModelCapability,
      connectionTargets,
      taskKinds,
      connectionTarget,
      addConnection,
      updateConnectionField,
      removeConnection,
      unlinkProfile,
      linkConnectionToServices,
      llmContextDetection,
      applyDetectedContextWindow,
      applying,
      saveRegistry,
      logs,
      testRunning,
      modelTests,
      diagnosticsResults,
      embeddingCapabilities,
      runDetailedTest,
      embeddingDefaultDim,
    ],
  );

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
}
