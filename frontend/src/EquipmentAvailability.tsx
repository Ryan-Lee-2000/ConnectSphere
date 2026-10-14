import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

type Assessment = {
  requirement_id: number;
  event: { id: number; name: string; date: string | null };
  equipment_type: { id: number; name: string; location: string | null };
  requirement_status: string;
  required_quantity: number;
  required_start_date: string;
  required_end_date: string;
  commitment_start: string;
  commitment_end: string;
  reserved_quantity: number;
  available_to_reserve: number;
  shortfall: number;
  overcommitted_units: number;
  unavailability_history?: Array<{
    id: number;
    action: 'marked_unavailable' | 'restored_to_requested';
    reason: string | null;
    alternative_suggestion: string | null;
    recorded_at: string;
    recorded_by: { id: string; name: string | null };
  }>;
};

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : 'Not recorded';
}

function requirementIndicator(item: Assessment) {
  const remaining = Math.max(0, item.required_quantity - item.reserved_quantity);
  const held = `${item.reserved_quantity} of ${item.required_quantity} units held`;
  // A Review Required line must keep its revalidation control, even when it is also overcommitted.
  // The warning is included in the detail so staff can see both the workflow state and its reason.
  if (item.requirement_status === 'review_required') return { detail: item.overcommitted_units > 0 ? `${item.overcommitted_units} ${item.overcommitted_units === 1 ? 'unit is' : 'units are'} overcommitted` : 'Confirm retained stock', held, label: 'Review required', tone: 'review' };
  // A stock reduction can make an otherwise complete retained reservation unsafe. Surface that
  // live availability warning before a persisted Reserved state so staff never see false success.
  if (item.overcommitted_units > 0 && item.reserved_quantity > 0) return { detail: `${item.overcommitted_units} ${item.overcommitted_units === 1 ? 'unit is' : 'units are'} overcommitted`, held, label: 'Stock overcommitted', tone: 'review' };
  if (item.requirement_status === 'reserved') return { detail: 'Fully covered', held, label: 'Reserved', tone: 'complete' };
  if (item.requirement_status === 'unavailable') return { detail: 'Cannot be reserved yet', held, label: 'Unavailable', tone: 'attention' };
  if (item.requirement_status === 'partially_reserved') return { detail: `${remaining} ${remaining === 1 ? 'unit' : 'units'} still required`, held, label: 'Partially reserved', tone: 'attention' };
  if (item.shortfall > 0) return { detail: `Stock is short by ${item.shortfall}`, held, label: 'Requested', tone: 'attention' };
  return { detail: `${remaining} ${remaining === 1 ? 'unit' : 'units'} to arrange`, held, label: 'Requested', tone: 'neutral' };
}

export function EquipmentAvailability({ accessToken, request }: { accessToken: string; request?: ApiRequest }) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [items, setItems] = useState<Assessment[] | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [quantityDrafts, setQuantityDrafts] = useState<Record<number, string>>({});
  const [releaseQuantityDrafts, setReleaseQuantityDrafts] = useState<Record<number, string>>({});
  const [releaseReasonDrafts, setReleaseReasonDrafts] = useState<Record<number, string>>({});
  const [unavailableReasonDrafts, setUnavailableReasonDrafts] = useState<Record<number, string>>({});
  const [alternativeSuggestionDrafts, setAlternativeSuggestionDrafts] = useState<Record<number, string>>({});
  const [actionError, setActionError] = useState<Record<number, string>>({});
  const [busyRequirement, setBusyRequirement] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await api('/api/equipment-availability');
        if (!response.ok) throw new Error(await responseError(response, 'Could not load equipment availability.'));
        const body = await response.json() as { assessments: Assessment[]; input_notice: string };
        if (active) { setItems(body.assessments); setNotice(body.input_notice); }
      } catch (reason) { if (active) setError(reason instanceof Error ? reason.message : 'Could not load equipment availability.'); }
    })();
    return () => { active = false; };
  }, [api]);

  async function reload() {
    const response = await api('/api/equipment-availability');
    if (!response.ok) throw new Error(await responseError(response, 'Could not refresh equipment availability.'));
    const body = await response.json() as { assessments: Assessment[]; input_notice: string };
    setItems(body.assessments);
    setNotice(body.input_notice);
  }

  async function reserve(item: Assessment) {
    const requestedQuantity = Number(quantityDrafts[item.requirement_id] || '');
    const maximum = Math.min(item.required_quantity - item.reserved_quantity, item.available_to_reserve);
    if (!Number.isInteger(requestedQuantity) || requestedQuantity < 1 || requestedQuantity > maximum) {
      setActionError(current => ({ ...current, [item.requirement_id]: `Enter a whole number from 1 to ${maximum}.` }));
      return;
    }
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/equipment-requirements/${item.requirement_id}/reservations`, {
        method: 'POST', body: JSON.stringify({ quantity: requestedQuantity }),
      });
      if (!response.ok) throw new Error(await responseError(response, 'Equipment could not be reserved.'));
      setQuantityDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      await reload();
    } catch (reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason instanceof Error ? reason.message : 'Equipment could not be reserved.' }));
    } finally { setBusyRequirement(null); }
  }

  async function revalidate(item: Assessment) {
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/equipment-requirements/${item.requirement_id}/revalidate-reservation`, { method: 'POST' });
      if (!response.ok) throw new Error(await responseError(response, 'The reservation could not be revalidated.'));
      await reload();
    } catch (reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason instanceof Error ? reason.message : 'The reservation could not be revalidated.' }));
    } finally { setBusyRequirement(null); }
  }

  async function release(item: Assessment) {
    const quantity = Number(releaseQuantityDrafts[item.requirement_id] || '');
    const reason = (releaseReasonDrafts[item.requirement_id] || '').trim();
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > item.reserved_quantity) {
      setActionError(current => ({ ...current, [item.requirement_id]: `Enter a whole number from 1 to ${item.reserved_quantity}.` }));
      return;
    }
    if (!reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: 'Enter a reason for this release.' }));
      return;
    }
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/equipment-requirements/${item.requirement_id}/releases`, {
        method: 'POST', body: JSON.stringify({ quantity, reason }),
      });
      if (!response.ok) throw new Error(await responseError(response, 'Equipment could not be released.'));
      setReleaseQuantityDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      setReleaseReasonDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      await reload();
    } catch (reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason instanceof Error ? reason.message : 'Equipment could not be released.' }));
    } finally { setBusyRequirement(null); }
  }

  async function releaseAllForEvent(item: Assessment) {
    const reason = (releaseReasonDrafts[item.requirement_id] || '').trim();
    if (!reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: 'Enter a reason before releasing this event’s equipment.' }));
      return;
    }
    if (!window.confirm(`Release all remaining equipment held for “${item.event.name}”? This keeps the reservation history.`)) return;
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/event-requests/${item.event.id}/equipment-releases`, {
        method: 'POST', body: JSON.stringify({ reason }),
      });
      if (!response.ok) throw new Error(await responseError(response, 'The event’s equipment could not be released.'));
      setReleaseQuantityDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      setReleaseReasonDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      await reload();
    } catch (reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason instanceof Error ? reason.message : 'The event’s equipment could not be released.' }));
    } finally { setBusyRequirement(null); }
  }

  async function markUnavailable(item: Assessment) {
    const reason = (unavailableReasonDrafts[item.requirement_id] || '').trim();
    const alternative_suggestion = (alternativeSuggestionDrafts[item.requirement_id] || '').trim();
    if (!reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: 'Enter a reason this requirement is unavailable.' }));
      return;
    }
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/equipment-requirements/${item.requirement_id}/mark-unavailable`, {
        method: 'POST', body: JSON.stringify({ reason, alternative_suggestion: alternative_suggestion || undefined }),
      });
      if (!response.ok) throw new Error(await responseError(response, 'The requirement could not be marked unavailable.'));
      setUnavailableReasonDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      setAlternativeSuggestionDrafts(current => ({ ...current, [item.requirement_id]: '' }));
      await reload();
    } catch (reason_) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason_ instanceof Error ? reason_.message : 'The requirement could not be marked unavailable.' }));
    } finally { setBusyRequirement(null); }
  }

  async function restoreRequested(item: Assessment) {
    setBusyRequirement(item.requirement_id);
    setActionError(current => ({ ...current, [item.requirement_id]: '' }));
    try {
      const response = await api(`/api/equipment-requirements/${item.requirement_id}/restore-requested`, { method: 'POST' });
      if (!response.ok) throw new Error(await responseError(response, 'The requirement could not be restored.'));
      await reload();
    } catch (reason) {
      setActionError(current => ({ ...current, [item.requirement_id]: reason instanceof Error ? reason.message : 'The requirement could not be restored.' }));
    } finally { setBusyRequirement(null); }
  }

  if (error) return <section className="equipment-availability"><p className="error" role="alert">{error}</p></section>;
  if (!items) return <p role="status">Loading equipment availability…</p>;

  const totalShortfall = items.reduce((sum, item) => sum + item.shortfall, 0);
  return <section className="equipment-availability" aria-labelledby="equipment-availability-title">
    <header className="equipment-availability__header">
      <div><p className="eyebrow">Technical support · planning</p><h1 id="equipment-availability-title">Equipment availability</h1>
        <p>Assess stock across each requirement’s full collection-to-return commitment period, then reserve feasible units for the event.</p></div>
      <dl className="equipment-availability__summary" aria-label="Availability summary">
        <div><dt>Requirements</dt><dd>{items.length}</dd></div>
        <div><dt>Shortfall</dt><dd>{totalShortfall}</dd></div>
      </dl>
    </header>
    <p className="equipment-availability__notice" role="status">{notice}</p>
    {items.length === 0 ? <section className="equipment-availability__empty"><h2>No mapped planning requirements</h2><p>Availability appears here after an Event Coordinator maps an equipment requirement to the catalogue.</p></section> : <div className="equipment-availability__list">
      {items.map((item, index) => {
        const indicator = requirementIndicator(item);
        return <article className="equipment-availability__card" key={item.requirement_id}>
        <header><div><p className="equipment-availability__event">{item.event.name} · {formatDate(item.event.date)}</p><h2>{item.equipment_type.name}</h2><p>{item.equipment_type.location || 'Storage location not recorded'}</p></div><div className={`equipment-availability__state equipment-availability__state--${indicator.tone}`}><span>Requirement state</span><strong>{indicator.label}</strong><b>{indicator.held}</b><small>{indicator.detail}</small></div></header>
        <dl className="equipment-availability__metrics">
          <div><dt>Required</dt><dd>{item.required_quantity}</dd></div><div><dt>Already reserved</dt><dd>{item.reserved_quantity}</dd></div><div><dt>Available to reserve</dt><dd>{item.available_to_reserve}</dd></div><div><dt>Shortfall</dt><dd>{item.shortfall}</dd></div>
        </dl>
        <dl className="equipment-availability__details equipment-availability__details--single">
          <div><dt>Commitment period</dt><dd>{formatDate(item.commitment_start)} – {formatDate(item.commitment_end)}</dd></div>
        </dl>
        <EquipmentReservationAction
          busy={busyRequirement === item.requirement_id}
          error={actionError[item.requirement_id]}
          firstForEvent={items.findIndex(candidate => candidate.event.id === item.event.id && candidate.reserved_quantity > 0) === index}
          item={item}
          onQuantityChange={value => setQuantityDrafts(current => ({ ...current, [item.requirement_id]: value }))}
          onRelease={() => void release(item)}
          onReleaseAll={() => void releaseAllForEvent(item)}
          onReleaseQuantityChange={value => setReleaseQuantityDrafts(current => ({ ...current, [item.requirement_id]: value }))}
          onReleaseReasonChange={value => setReleaseReasonDrafts(current => ({ ...current, [item.requirement_id]: value }))}
          onUnavailableReasonChange={value => setUnavailableReasonDrafts(current => ({ ...current, [item.requirement_id]: value }))}
          onAlternativeSuggestionChange={value => setAlternativeSuggestionDrafts(current => ({ ...current, [item.requirement_id]: value }))}
          onMarkUnavailable={() => void markUnavailable(item)}
          onRestoreRequested={() => void restoreRequested(item)}
          onRevalidate={() => void revalidate(item)}
          onReserve={() => void reserve(item)}
          quantity={quantityDrafts[item.requirement_id] || ''}
          releaseQuantity={releaseQuantityDrafts[item.requirement_id] || ''}
          releaseReason={releaseReasonDrafts[item.requirement_id] || ''}
          unavailableReason={unavailableReasonDrafts[item.requirement_id] || ''}
          alternativeSuggestion={alternativeSuggestionDrafts[item.requirement_id] || ''}
        />
      </article>;
      })}
    </div>}
  </section>;
}

function EquipmentReservationAction({ busy, error, firstForEvent, item, onQuantityChange, onRelease, onReleaseAll, onReleaseQuantityChange, onReleaseReasonChange, onUnavailableReasonChange, onAlternativeSuggestionChange, onMarkUnavailable, onRestoreRequested, onRevalidate, onReserve, quantity, releaseQuantity, releaseReason, unavailableReason, alternativeSuggestion }: {
  busy: boolean; error?: string; item: Assessment; onQuantityChange: (value: string) => void;
  firstForEvent: boolean; onRelease: () => void; onReleaseAll: () => void;
  onReleaseQuantityChange: (value: string) => void; onReleaseReasonChange: (value: string) => void;
  onUnavailableReasonChange: (value: string) => void; onAlternativeSuggestionChange: (value: string) => void;
  onMarkUnavailable: () => void; onRestoreRequested: () => void;
  onRevalidate: () => void; onReserve: () => void; quantity: string; releaseQuantity: string; releaseReason: string;
  unavailableReason: string; alternativeSuggestion: string;
}) {
  const remaining = item.required_quantity - item.reserved_quantity;
  const maximum = Math.min(remaining, item.available_to_reserve);
  const isReservable = ['requested', 'partially_reserved', 'review_required'].includes(item.requirement_status);
  const releaseControl = item.reserved_quantity > 0 ? <section className="equipment-availability__release-control" aria-label={`Release ${item.equipment_type.name}`}>
    <div className="equipment-availability__action-copy"><h3>Release held units</h3><p>Release only units no longer needed. The original reservation and this reason remain in history.</p></div>
    <label htmlFor={`release-quantity-${item.requirement_id}`}>Units to release
      <input id={`release-quantity-${item.requirement_id}`} min="1" max={item.reserved_quantity} onChange={event => onReleaseQuantityChange(event.target.value)} step="1" type="number" value={releaseQuantity} />
    </label>
    <label className="equipment-availability__release-reason" htmlFor={`release-reason-${item.requirement_id}`}>Release reason
      <input id={`release-reason-${item.requirement_id}`} maxLength={2000} onChange={event => onReleaseReasonChange(event.target.value)} value={releaseReason} />
    </label>
    <button className="button button--secondary" disabled={busy} onClick={onRelease} type="button">{busy ? 'Releasing…' : 'Release units'}</button>
    {firstForEvent && <button className="button button--secondary" disabled={busy} onClick={onReleaseAll} type="button">{busy ? 'Releasing…' : 'Release all for event'}</button>}
  </section> : null;
  // Review Required remains actionable. Staff need the revalidation button to receive the
  // server's current feasibility decision, rather than an overcommitment banner that blocks it.
  if (item.requirement_status === 'review_required') return <footer className="equipment-availability__action">
    <div className="equipment-availability__action-copy"><h3>Review retained reservation</h3><p>{item.overcommitted_units > 0 ? <>Current stock is overcommitted by {item.overcommitted_units} {item.overcommitted_units === 1 ? 'unit' : 'units'}. Revalidate to confirm whether the retained reservation can remain.</> : 'Revalidate retained units against current stock before making another reservation.'}</p></div>
    <button className="button button--secondary" disabled={busy} onClick={onRevalidate} type="button">{busy ? 'Revalidating…' : 'Revalidate availability'}</button>
    <div className="equipment-availability__reserve-control"><label htmlFor={`reserve-${item.requirement_id}`}>Units to reserve<input disabled={maximum === 0} id={`reserve-${item.requirement_id}`} max={Math.max(1, maximum)} min="1" onChange={event => onQuantityChange(event.target.value)} step="1" type="number" value={quantity} /></label><button className="button button--primary" disabled={busy || maximum === 0} onClick={onReserve} type="button">{busy ? 'Reserving…' : maximum === 0 ? 'No units available' : 'Reserve units'}</button></div>
    {releaseControl}{error && <p className="error equipment-availability__action-error" role="alert">{error}</p>}
  </footer>;
  if (item.overcommitted_units > 0 && item.reserved_quantity > 0) return <footer className="equipment-availability__action"><p><strong>Stock overcommitted.</strong> {item.overcommitted_units} {item.overcommitted_units === 1 ? 'unit is' : 'units are'} committed beyond current stock. The {item.reserved_quantity} retained {item.reserved_quantity === 1 ? 'unit remains' : 'units remain'} held while Technical Support resolves the stock conflict.</p>{releaseControl}{error && <p className="error equipment-availability__action-error" role="alert">{error}</p>}</footer>;
  if (item.requirement_status === 'reserved') return <footer className="equipment-availability__action"><p><strong>Reservation complete.</strong> All required units are held for this event’s commitment period.</p>{releaseControl}{error && <p className="error equipment-availability__action-error" role="alert">{error}</p>}</footer>;
  if (item.requirement_status === 'unavailable') {
    const original = [...(item.unavailability_history || [])].reverse().find(entry => entry.action === 'marked_unavailable');
    return <footer className="equipment-availability__action">
      <p><strong>Unavailable requirement.</strong> {original?.reason || 'A reason was recorded.'}</p>
      {original?.alternative_suggestion && <p><strong>Suggested alternative:</strong> {original.alternative_suggestion}</p>}
      <p>Restoring makes this requirement Requested again. Its unavailable decision remains in history.</p>
      <button className="button button--secondary" disabled={busy} onClick={onRestoreRequested} type="button">{busy ? 'Restoring…' : 'Restore to requested'}</button>
      {error && <p className="error equipment-availability__action-error" role="alert">{error}</p>}
    </footer>;
  }
  const unavailableControl = item.requirement_status === 'requested' && item.reserved_quantity === 0 ? <section className="equipment-availability__unavailable-control" aria-label={`Mark ${item.equipment_type.name} unavailable`}>
    <div className="equipment-availability__action-copy"><h3>Mark requirement unavailable</h3><p>Use this when this event requirement cannot currently be fulfilled. This does not remove physical stock or alter other reservations.</p></div>
    <label htmlFor={`unavailable-reason-${item.requirement_id}`}>Reason
      <input id={`unavailable-reason-${item.requirement_id}`} maxLength={2000} onChange={event => onUnavailableReasonChange(event.target.value)} value={unavailableReason} />
    </label>
    <label htmlFor={`alternative-suggestion-${item.requirement_id}`}>Alternative suggestion (optional)
      <input id={`alternative-suggestion-${item.requirement_id}`} maxLength={2000} onChange={event => onAlternativeSuggestionChange(event.target.value)} value={alternativeSuggestion} />
    </label>
    <button className="button button--secondary" disabled={busy} onClick={onMarkUnavailable} type="button">{busy ? 'Saving…' : 'Mark unavailable'}</button>
  </section> : null;
  return <footer className="equipment-availability__action">
    <div className="equipment-availability__action-copy"><h3>Reserve units</h3><p>{maximum > 0 ? `Up to ${maximum} additional ${maximum === 1 ? 'unit is' : 'units are'} available to reserve now.` : 'No additional units are available for this full commitment period.'}</p></div>
    {isReservable && <div className="equipment-availability__reserve-control">
      <label htmlFor={`reserve-${item.requirement_id}`}>Units to reserve<input disabled={maximum === 0} id={`reserve-${item.requirement_id}`} max={Math.max(1, maximum)} min="1" onChange={event => onQuantityChange(event.target.value)} step="1" type="number" value={quantity} /></label>
      <button className="button button--primary" disabled={busy || maximum === 0} onClick={onReserve} type="button">{busy ? 'Reserving…' : maximum === 0 ? 'No units available' : 'Reserve units'}</button>
    </div>}
    {unavailableControl}{releaseControl}{error && <p className="error equipment-availability__action-error" role="alert">{error}</p>}
  </footer>;
}
