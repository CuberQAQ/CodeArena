import { useParams } from "react-router-dom";

export default function ContestDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <h1 className="text-2xl font-bold text-foreground">Contest In Progress</h1>
      <p className="mt-2 text-muted-foreground">Contest ID: {id}</p>
    </div>
  );
}
