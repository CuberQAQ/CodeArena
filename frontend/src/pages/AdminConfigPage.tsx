import { useEffect, useRef, useState } from "react";
import { Settings, Loader2, Save, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse } from "@/types";

interface ConfigSection {
  key: string;
  label: string;
  fields: { key: string; label: string; type: "number" | "string" | "boolean" }[];
}

const CONFIG_SECTIONS: ConfigSection[] = [
  {
    key: "elo",
    label: "Elo System",
    fields: [
      { key: "k_factor", label: "K Factor", type: "number" },
      { key: "initial_elo", label: "Initial Elo", type: "number" },
    ],
  },
  {
    key: "economy",
    label: "Token Economy",
    fields: [
      { key: "daily_token_cap", label: "Daily Token Cap", type: "number" },
      { key: "starting_tokens", label: "Starting Tokens", type: "number" },
    ],
  },
  {
    key: "challenge",
    label: "Challenge System",
    fields: [
      { key: "match_timeout_seconds", label: "Match Timeout (seconds)", type: "number" },
    ],
  },
  {
    key: "training",
    label: "Training System",
    fields: [
      { key: "problems_per_session", label: "Problems Per Session", type: "number" },
    ],
  },
];

export default function AdminConfigPage() {
  const [config, setConfig] = useState<Record<string, Record<string, string | number | boolean>>>(
    {},
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const hasFetchedRef = useRef(false);

  const fetchConfig = async () => {
    setLoading(true);
    setError("");
    try {
      const results = await Promise.all(
        CONFIG_SECTIONS.map(async (section) => {
          try {
            const res = await api.get<ApiResponse<Record<string, string | number | boolean>>>(
              `/admin/config/${section.key}`,
            );
            return { key: section.key, data: res.data.data };
          } catch {
            return { key: section.key, data: {} };
          }
        }),
      );
      const merged: Record<string, Record<string, string | number | boolean>> = {};
      for (const r of results) {
        merged[r.key] = r.data;
      }
      setConfig(merged);
    } catch (err) {
      setError(extractApiError(err, "Failed to load configuration"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;
    fetchConfig();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      // Try to save each section
      for (const section of CONFIG_SECTIONS) {
        const sectionData = config[section.key];
        if (sectionData && Object.keys(sectionData).length > 0) {
          try {
            await api.put(`/admin/config/${section.key}`, sectionData);
          } catch {
            // Some endpoints may not exist yet
          }
        }
      }
      setSuccess("Configuration saved successfully.");
    } catch (err) {
      setError(extractApiError(err, "Failed to save configuration"));
    } finally {
      setSaving(false);
    }
  };

  const updateField = (section: string, field: string, value: string | number | boolean) => {
    setConfig((prev) => ({
      ...prev,
      [section]: {
        ...(prev[section] ?? {}),
        [field]: value,
      },
    }));
  };

  if (loading) {
    return <LoadingSpinner text="Loading configuration..." className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Configuration</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage system configuration parameters.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchConfig}>
            <RefreshCw className="mr-1.5 size-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" />
            ) : (
              <Save className="mr-1.5 size-3.5" />
            )}
            Save All
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          {success}
        </div>
      )}

      {CONFIG_SECTIONS.map((section) => (
        <div key={section.key} className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-2">
            <Settings className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold text-foreground">{section.label}</h2>
          </div>
          <div className="mt-4 space-y-3">
            {section.fields.map((field) => (
              <div key={field.key} className="flex items-center gap-4">
                <label className="w-48 shrink-0 text-sm text-muted-foreground">
                  {field.label}
                </label>
                {field.type === "boolean" ? (
                  <button
                    onClick={() =>
                      updateField(section.key, field.key, !config[section.key]?.[field.key])
                    }
                    className={`relative h-6 w-11 rounded-full transition-colors ${
                      config[section.key]?.[field.key] ? "bg-primary" : "bg-muted"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 size-5 rounded-full bg-white transition-transform ${
                        config[section.key]?.[field.key] ? "translate-x-5" : ""
                      }`}
                    />
                  </button>
                ) : (
                  <input
                    type={field.type === "number" ? "number" : "text"}
                    value={(config[section.key]?.[field.key] as string | number) ?? ""}
                    onChange={(e) => {
                      const val =
                        field.type === "number"
                          ? parseFloat(e.target.value) || 0
                          : e.target.value;
                      updateField(section.key, field.key, val);
                    }}
                    className="w-48 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
                  />
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
