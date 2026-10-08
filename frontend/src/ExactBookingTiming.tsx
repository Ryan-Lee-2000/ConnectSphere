export type BookingTiming = {
  event: { start: string; end: string }; occupied: { start: string; end: string };
  setup_minutes: number; turnaround_minutes: number; venue_revision: number;
};
const formatter = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Singapore', hourCycle: 'h23' });
export const bookingInterval = (interval: { start: string; end: string }) => `${formatter.format(new Date(interval.start))} to ${formatter.format(new Date(interval.end))} SGT`;
export function ExactBookingTiming({ timing }: { timing: BookingTiming }) {
  return <dl aria-label="Recorded booking times">
    <div><dt>Advertised event</dt><dd>{bookingInterval(timing.event)}</dd></div>
    <div><dt>Full occupied interval</dt><dd>{bookingInterval(timing.occupied)}</dd></div>
    <div><dt>Preparation</dt><dd>Setup {timing.setup_minutes} min · Turnaround {timing.turnaround_minutes} min</dd></div>
  </dl>;
}
export function BookingReviewReasons({ reasons }: { reasons?: string[] }) {
  return reasons?.length ? <div role="note"><strong>Review required</strong><ul>{reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></div> : null;
}
