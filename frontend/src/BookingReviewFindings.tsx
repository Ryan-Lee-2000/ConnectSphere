export type ReviewOccupancy = {
  start?: string;
  end?: string;
  legacy_slots?: { date: string; slot: string; kind: string }[];
};

export type BookingReviewFinding = {
  id: number;
  reason_type: 'overlap' | 'operational_block' | 'outside_operating_hours' | 'unresolved_historical_timing';
  detail: string;
  original_occupancy: ReviewOccupancy | null;
  current_occupancy: ReviewOccupancy | null;
  venue_timing_revision: number;
  first_assessed_at: string;
  last_assessed_at: string;
};

const instant = (value: string) => new Intl.DateTimeFormat('en-SG', {
  day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  timeZone: 'Asia/Singapore',
}).format(new Date(value));

export function occupancyName(occupancy: ReviewOccupancy | null) {
  if (!occupancy) return 'Not resolved';
  if (occupancy.start && occupancy.end) return `${instant(occupancy.start)} – ${instant(occupancy.end)}`;
  if (occupancy.legacy_slots?.length) {
    return occupancy.legacy_slots.map(slot => `${slot.date} ${slot.slot} (${slot.kind})`).join(', ');
  }
  return 'Not resolved';
}

export function BookingReviewFindings({ findings }: { findings: BookingReviewFinding[] }) {
  if (!findings.length) return null;
  return <section className="booking-review-findings" aria-labelledby="timing-findings-title">
    <h2 id="timing-findings-title">Timing review findings</h2>
    <ul>
      {findings.map(finding => <li key={finding.id}>
        <strong>{finding.detail}</strong>
        <dl>
          <div><dt>Original occupancy</dt><dd>{occupancyName(finding.original_occupancy)}</dd></div>
          <div><dt>Under current rules</dt><dd>{occupancyName(finding.current_occupancy)}</dd></div>
        </dl>
      </li>)}
    </ul>
  </section>;
}
