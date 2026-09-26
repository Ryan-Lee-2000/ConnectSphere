export type Clarification = {
  id: number;
  message: string;
  author: { id: string; name: string };
  created_at: string;
};

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat('en-SG', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Singapore' }).format(parsed);
}

// Newest first, as the API returns it, so the latest question is read before the earlier ones.
export function ClarificationHistory({ clarifications, heading }: { clarifications: Clarification[]; heading: string }) {
  if (clarifications.length === 0) return null;
  return <section className="clarification-history" aria-labelledby="clarification-history-title">
    <h2 id="clarification-history-title">{heading}</h2>
    <ol className="clarification-history__list">{clarifications.map(item => <li key={item.id}>
      <p className="clarification-history__meta">{item.author.name} · {formatTimestamp(item.created_at)}</p>
      <p className="clarification-history__message">{item.message}</p>
    </li>)}</ol>
  </section>;
}
