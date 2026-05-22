import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Settings,
  Loader2,
  Save,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  ArrowLeft,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConfigField {
  key: string;
  label: string;
  type: string;
  default: unknown;
}

interface ConfigSection {
  key: string;
  label: string;
  fields: ConfigField[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Flatten the nested config into dot-path keys
function flattenConfig(obj: Record<string, unknown>, prefix = ""): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.assign(result, flattenConfig(value as Record<string, unknown>, fullKey));
    } else {
      result[fullKey] = value;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AdminConfigPage() {
  const { t } = useTranslation(["admin", "common"]);
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [metadata, setMetadata] = useState<ConfigSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<Record<string, string>>({});
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({});
  const [dirtyKeys, setDirtyKeys] = useState<Set<string>>(new Set());
  const [originalConfig, setOriginalConfig] = useState<Record<string, unknown>>({});
  const hasFetchedRef = useRef(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [configRes, metaRes] = await Promise.all([
        api.get<ApiResponse<Record<string, unknown>>>("/admin/config"),
        api.get<ApiResponse<ConfigSection[]>>("/admin/config/metadata"),
      ]);
      const flatConfig = flattenConfig(configRes.data.data);
      setConfig(flatConfig);
      setOriginalConfig(flatConfig);
      setMetadata(metaRes.data.data);

      // Expand first section by default
      if (metaRes.data.data.length > 0) {
        setExpandedSections((prev) => ({
          ...prev,
          [metaRes.data.data[0].key]: true,
        }));
      }
      setDirtyKeys(new Set());
    } catch (err) {
      setError(extractApiError(err, t("admin:failedLoadConfig")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;
    fetchData();
  }, [fetchData]);

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const updateField = (key: string, value: unknown) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    setDirtyKeys((prev) => {
      const next = new Set(prev);
      const originalValue = originalConfig[key];
      if (value === originalValue || (typeof value === "number" && typeof originalValue === "number" && value === originalValue)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleSaveField = async (key: string) => {
    setSaving((prev) => ({ ...prev, [key]: true }));
    setSuccess((prev) => ({ ...prev, [key]: "" }));
    try {
      await api.put(`/admin/config/${key}`, { value: config[key] });
      setSuccess((prev) => ({ ...prev, [key]: t("admin:saved") }));
      setOriginalConfig((prev) => ({ ...prev, [key]: config[key] }));
      setDirtyKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      // Auto-clear success after 3s
      setTimeout(() => {
        setSuccess((prev) => ({ ...prev, [key]: "" }));
      }, 3000);
    } catch (err) {
      setSuccess((prev) => ({ ...prev, [key]: "" }));
      setError(extractApiError(err, t("failedSaveField", { key })));
    } finally {
      setSaving((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleResetField = async (key: string) => {
    setSaving((prev) => ({ ...prev, [key]: true }));
    setSuccess((prev) => ({ ...prev, [key]: "" }));
    try {
      const res = await api.post(`/admin/config/${key}/reset`);
      const defaultValue = res.data.data.value;
      setConfig((prev) => ({ ...prev, [key]: defaultValue }));
      setOriginalConfig((prev) => ({ ...prev, [key]: defaultValue }));
      setSuccess((prev) => ({ ...prev, [key]: t("admin:resetToDefaultMsg") }));
      setDirtyKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      setTimeout(() => {
        setSuccess((prev) => ({ ...prev, [key]: "" }));
      }, 3000);
    } catch (err) {
      setError(extractApiError(err, t("failedResetField", { key })));
    } finally {
      setSaving((prev) => ({ ...prev, [key]: false }));
    }
  };

  const renderInput = (field: ConfigField) => {
    const value = config[field.key];

    if (field.type === "list") {
      // Array values: display as read-only for now
      return (
        <div className="flex items-center gap-3">
          <code className="flex-1 rounded-lg border border-input bg-muted px-3 py-1.5 text-xs text-foreground">
            {JSON.stringify(value ?? field.default)}
          </code>
        </div>
      );
    }

    if (field.type === "bool" || field.type === "boolean") {
      return (
        <div className="flex items-center gap-3">
          <button
            onClick={() => updateField(field.key, !value)}
            className={`relative h-6 w-11 rounded-full transition-colors ${
              value ? "bg-primary" : "bg-muted"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 size-5 rounded-full bg-white transition-transform ${
                value ? "translate-x-5" : ""
              }`}
            />
          </button>
          <span className="text-xs text-muted-foreground">
            {value ? t("common:enabled", { ns: "common" }) : t("common:disabled", { ns: "common" })}
          </span>
        </div>
      );
    }

    if (field.type === "int" || field.type === "float") {
      return (
        <input
          type="number"
          step={field.type === "float" ? "0.01" : "1"}
          value={(value as number | string) ?? ""}
          onChange={(e) => {
            const numVal = field.type === "float" ? parseFloat(e.target.value) : parseInt(e.target.value, 10);
            updateField(field.key, isNaN(numVal) ? e.target.value : numVal);
          }}
          className="w-36 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
        />
      );
    }

    // string or unknown
    return (
      <input
        type="text"
        value={(value as string) ?? ""}
        onChange={(e) => updateField(field.key, e.target.value)}
        className="w-48 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
      />
    );
  };

  if (loading) {
    return <LoadingSpinner text={t("admin:loadingConfig")} className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center gap-4">
        <Link
          to="/admin"
          className="flex size-8 items-center justify-center rounded-lg border border-border transition-colors hover:bg-muted"
        >
          <ArrowLeft className="size-4 text-muted-foreground" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-foreground">{t("admin:configPage")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("admin:configPageDesc")}
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
          <button
            onClick={() => setError("")}
            className="ml-2 underline hover:no-underline"
          >
            {t("common:dismiss", { ns: "common" })}
          </button>
        </div>
      )}

      {dirtyKeys.size > 0 && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          {t("common:unsavedChanges", { ns: "common", count: dirtyKeys.size })}
        </div>
      )}

      {metadata.map((section) => {
        const isExpanded = expandedSections[section.key] ?? false;
        const sectionDirtyCount = section.fields.filter((f) => dirtyKeys.has(f.key)).length;

        return (
          <div key={section.key} className="rounded-xl border border-border bg-card">
            {/* Section Header */}
            <button
              onClick={() => toggleSection(section.key)}
              className="flex w-full items-center justify-between p-5 text-left"
            >
              <div className="flex items-center gap-2">
                {isExpanded ? (
                  <ChevronDown className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="size-4 text-muted-foreground" />
                )}
                <Settings className="size-4 text-muted-foreground" />
                <h2 className="text-sm font-semibold text-foreground">{section.label}</h2>
                {sectionDirtyCount > 0 && (
                  <span className="rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs text-yellow-400">
                    {sectionDirtyCount}
                  </span>
                )}
              </div>
              <span className="text-xs text-muted-foreground">
                {t("admin:fields", { count: section.fields.length })}
              </span>
            </button>

            {/* Section Body */}
            {isExpanded && (
              <div className="border-t border-border px-5 pb-5">
                <div className="mt-4 space-y-4">
                  {section.fields.map((field) => {
                    const isDirty = dirtyKeys.has(field.key);
                    const isSaving = saving[field.key];
                    const isSuccess = success[field.key];

                    return (
                      <div key={field.key}>
                        <div className="flex items-center gap-4">
                          <label className="w-56 shrink-0 text-sm text-muted-foreground">
                            {field.label}
                            <span className="ml-1 text-xs text-muted-foreground/60">
                              ({field.type})
                            </span>
                          </label>
                          {renderInput(field)}
                          <div className="flex items-center gap-1">
                            {isDirty && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => handleSaveField(field.key)}
                                disabled={isSaving}
                                className="h-7 px-2"
                              >
                                {isSaving ? (
                                  <Loader2 className="size-3 animate-spin" />
                                ) : (
                                  <Save className="size-3" />
                                )}
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleResetField(field.key)}
                              disabled={isSaving}
                              title={t("admin:resetToDefault")}
                              className="h-7 px-2"
                            >
                              <RotateCcw className="size-3 text-muted-foreground" />
                            </Button>
                          </div>
                        </div>
                        {/* Success message inline */}
                        {isSuccess && (
                          <p className="ml-60 mt-1 text-xs text-green-400">{isSuccess}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
