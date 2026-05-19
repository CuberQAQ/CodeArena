import { useAuthStore } from "@/stores/auth";

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);

  return (
    <div>
      <h1 className="text-2xl font-bold text-foreground">Profile</h1>
      {user ? (
        <div className="mt-4 space-y-2">
          <p className="text-sm text-muted-foreground">Username: {user.username}</p>
          <p className="text-sm text-muted-foreground">Email: {user.email}</p>
          <p className="text-sm text-muted-foreground">Elo: {user.elo}</p>
          <p className="text-sm text-muted-foreground">PP: {user.pp}</p>
          <p className="text-sm text-muted-foreground">Tokens: {user.tokens}</p>
        </div>
      ) : (
        <p className="mt-2 text-muted-foreground">Loading profile...</p>
      )}
    </div>
  );
}
