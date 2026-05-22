import { useState, useRef, useEffect, useCallback } from "react";
import { User, Camera, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import api from "@/services/api";

// ---------------------------------------------------------------------------
// Avatar display component (used everywhere avatars are shown)
// ---------------------------------------------------------------------------

interface AvatarProps {
  userId?: string;
  src?: string | null;
  size?: number;
  className?: string;
}

/**
 * Displays a user avatar or a default placeholder.
 *
 * - `src`: optional avatar_path (from leaderboard / settings). When present,
 *   the component constructs a full URL via the /api/v1/auth/avatar/{userId} endpoint.
 * - `userId`: required for constructing the avatar URL when src is set.
 * - If no avatar is available, shows a default User icon on a gray background.
 */
export function Avatar({ userId, src, size = 40, className = "" }: AvatarProps) {
  const [imgError, setImgError] = useState(false);

  // Build the avatar URL if we have both userId and an avatar path
  // Even without src, we try to load from the endpoint -- if it 404s, the
  // onError handler shows the placeholder
  const avatarUrl = userId ? `/api/v1/auth/avatar/${userId}` : null;
  const shouldShowImage = (avatarUrl || src) && !imgError;

  // Reset error state when userId changes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset image error on userId change
    setImgError(false);
  }, [userId]);

  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-full bg-muted ${className}`}
      style={{ width: size, height: size }}
    >
      {shouldShowImage ? (
        <img
          src={avatarUrl ?? undefined}
          alt="Avatar"
          className="h-full w-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-muted">
          <User
            className="text-muted-foreground"
            style={{ width: size * 0.5, height: size * 0.5 }}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Avatar upload component (used on ProfilePage)
// ---------------------------------------------------------------------------

interface AvatarUploadProps {
  userId: string;
  size?: number;
  onUploaded?: () => void;
}

/**
 * Clickable avatar that triggers file selection and uploads the chosen image.
 * Shows a camera overlay on hover.
 */
export function AvatarUpload({ userId, size = 80, onUploaded }: AvatarUploadProps) {
  const { t } = useTranslation("common");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  // Try to load the current avatar on mount
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load avatar URL on userId change
    setAvatarUrl(`/api/v1/auth/avatar/${userId}`);
    setImgError(false);
  }, [userId]);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      // Client-side validation
      if (!["image/jpeg", "image/png"].includes(file.type)) {
        setError(t("avatar.invalidFormat"));
        return;
      }
      if (file.size > 2 * 1024 * 1024) {
        setError(t("avatar.fileTooLarge"));
        return;
      }

      setError("");
      setUploading(true);

      try {
        const formData = new FormData();
        formData.append("file", file);

        await api.post("/auth/avatar", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });

        // Force avatar refresh by busting cache
        setImgError(false);
        setAvatarUrl(`/api/v1/auth/avatar/${userId}?t=${Date.now()}`);
        onUploaded?.();
      } catch (err) {
        const msg =
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
          t("avatar.uploadFailed");
        setError(msg);
      } finally {
        setUploading(false);
        // Reset input so the same file can be re-selected
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }
    },
    [userId, onUploaded, t],
  );

  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={() => !uploading && fileInputRef.current?.click()}
        className="group relative shrink-0 overflow-hidden rounded-full transition-opacity hover:opacity-90"
        style={{ width: size, height: size }}
        disabled={uploading}
        title={t("avatar.clickToUpload")}
      >
        {avatarUrl && !imgError ? (
          <img
            src={avatarUrl}
            alt="Avatar"
            className="h-full w-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-primary/10">
            <User
              className="text-primary"
              style={{ width: size * 0.45, height: size * 0.45 }}
            />
          </div>
        )}

        {/* Overlay on hover */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
          {uploading ? (
            <Loader2 className="size-5 animate-spin text-white" />
          ) : (
            <Camera className="size-5 text-white" />
          )}
        </div>
      </button>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png"
        className="hidden"
        onChange={handleFileChange}
      />

      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}
