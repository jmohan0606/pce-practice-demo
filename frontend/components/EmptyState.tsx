export default function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {message ? <p>{message}</p> : null}
    </div>
  );
}
