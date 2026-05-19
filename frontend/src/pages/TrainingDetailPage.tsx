import { useParams } from "react-router-dom";

export default function TrainingDetailPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div>
      <h1 className="text-2xl font-bold text-foreground">Training Session</h1>
      <p className="mt-2 text-muted-foreground">
        Training session for topic: {id}
      </p>
    </div>
  );
}
