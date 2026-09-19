// Mirrors backend/app/slots.py — the single source of truth for the AM/PM/Night
// venue-operating-slot vocabulary shared by the venue catalogue and event requests.

export const SLOTS = [
  { key: 'AM', label: 'AM · 7am–12pm', start: '07:00', end: '12:00' },
  { key: 'PM', label: 'PM · 1pm–6pm', start: '13:00', end: '18:00' },
  // The backend's HH:MM time validator rejects "24:00"; 23:59 is the practical upper bound
  // used server-side (app/slots.py treats NIGHT as open-ended up to end of day).
  { key: 'NIGHT', label: 'Night · 7pm–12am', start: '19:00', end: '23:59' },
] as const;

export type SlotKey = (typeof SLOTS)[number]['key'];

export function slotLabel(key: string): string {
  return SLOTS.find(slot => slot.key === key)?.label ?? key;
}
