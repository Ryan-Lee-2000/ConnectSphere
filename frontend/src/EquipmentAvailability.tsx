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
};

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : 'Not recorded';
}

function statusLabel(value: string) { return value.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()); }

export function EquipmentAvailability({ accessToken, request }: { accessToken: string; request?: ApiRequest }) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [items, setItems] = useState<Assessment[] | null>(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState<string | null>(null);

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

  if (error) return <section className="equipment-availability"><p className="error" role="alert">{error}</p></section>;
  if (!items) return <p role="status">Loading equipment availability…</p>;

  const totalShortfall = items.reduce((sum, item) => sum + item.shortfall, 0);
  return <section className="equipment-availability" aria-labelledby="equipment-availability-title">
    <header className="equipment-availability__header">
      <div><p className="eyebrow">Technical support · planning</p><h1 id="equipment-availability-title">Equipment availability</h1>
        <p>Assess stock across each requirement’s full collection-to-return commitment period. This view is read-only; reserving units is handled in the next workflow.</p></div>
      <dl className="equipment-availability__summary" aria-label="Availability summary">
        <div><dt>Requirements</dt><dd>{items.length}</dd></div>
        <div><dt>Shortfall</dt><dd>{totalShortfall}</dd></div>
      </dl>
    </header>
    <p className="equipment-availability__notice" role="status">{notice}</p>
    {items.length === 0 ? <section className="equipment-availability__empty"><h2>No mapped planning requirements</h2><p>Availability appears here after an Event Coordinator maps an equipment requirement to the catalogue.</p></section> : <div className="equipment-availability__list">
      {items.map(item => <article className="equipment-availability__card" key={item.requirement_id}>
        <header><div><p className="equipment-availability__event">{item.event.name} · {formatDate(item.event.date)}</p><h2>{item.equipment_type.name}</h2><p>{item.equipment_type.location || 'Storage location not recorded'}</p></div><span className={`equipment-availability__outcome${item.shortfall > 0 || item.overcommitted_units > 0 ? ' equipment-availability__outcome--attention' : ''}`}>{item.shortfall > 0 ? `${item.shortfall} short` : 'Available'}</span></header>
        <dl className="equipment-availability__metrics">
          <div><dt>Required</dt><dd>{item.required_quantity}</dd></div><div><dt>Already reserved</dt><dd>{item.reserved_quantity}</dd></div><div><dt>Available to reserve</dt><dd>{item.available_to_reserve}</dd></div><div><dt>Shortfall</dt><dd>{item.shortfall}</dd></div>
        </dl>
        <dl className="equipment-availability__details">
          <div><dt>Commitment period</dt><dd>{formatDate(item.commitment_start)} – {formatDate(item.commitment_end)}</dd></div><div><dt>Requirement state</dt><dd>{statusLabel(item.requirement_status)}</dd></div>
        </dl>
      </article>)}
    </div>}
  </section>;
}
