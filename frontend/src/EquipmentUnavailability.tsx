import { useEffect, useMemo, useState } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

// SPL-96 (CS-E15-S3): Technical Support records units of an equipment type as unavailable, with a
// reason, and restores them later. The server owns every rule — the bounds (AC1), who may do it
// (AC6) and the resulting figures — so this panel only collects a quantity and a reason, shows the
// server's answer, and re-states the three stock figures it sends back.
//
// AC3-AC5 (the Review Required flag raised when usable stock falls below what is already reserved)
// belong to SPL-97 and are deliberately absent here. When SPL-97 lands, the flag and its reason are
// shown on the affected line; see docs/tasks/SPL-96.md.

type StockFigures = {
  id: number;
  name: string;
  total_stock: number;
  unavailable_units: number;
  usable_stock: number;
};

type Record = {
  id: number;
  action: 'marked_unavailable' | 'restored';
  quantity: number;
  reason: string;
  recorded_at: string | null;
};

const formatMoment = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('en-SG', {
        day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
      }).format(new Date(value))
    : 'Not recorded';

export function EquipmentUnavailability({ accessToken, equipmentTypeId, request }: {
  accessToken: string;
  equipmentTypeId: number;
  request?: ApiRequest;
}) {
  const api = useMemo(() => request || defaultRequest(accessToken), [request, accessToken]);
  const [stock, setStock] = useState<StockFigures | null>(null);
  const [history, setHistory] = useState<Record[]>([]);
  const [quantity, setQuantity] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const response = await api(`/api/equipment-types/${equipmentTypeId}/unavailability`);
        if (!response.ok) throw new Error(await responseError(response, 'Could not load unavailable units.'));
        const body = await response.json() as { equipment_type: StockFigures; history: Record[] };
        if (active) { setStock(body.equipment_type); setHistory(body.history); }
      } catch (reason_) {
        if (active) setLoadError(reason_ instanceof Error ? reason_.message : 'Could not load unavailable units.');
      }
    })();
    return () => { active = false; };
  }, [api, equipmentTypeId]);

  // One submit path for both directions: the only difference is which route it posts to, so the
  // validation, error handling and refreshed figures cannot drift between them.
  async function submit(action: 'unavailable-units' | 'restored-units') {
    if (saving) return;
    setSaving(true); setError(null); setConfirmation(null);
    try {
      const response = await api(`/api/equipment-types/${equipmentTypeId}/${action}`, {
        method: 'POST',
        // Sent as typed. The server decides what is a valid quantity (AC1), so a value this
        // panel would have rejected still comes back with the server's own message beside it.
        body: JSON.stringify({ quantity: Number(quantity), reason }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { setError(body.error || 'Could not record that. Try again.'); return; }
      setStock(body.equipment_type);
      setHistory(current => [body.record, ...current]);
      setQuantity(''); setReason('');
      setConfirmation(
        action === 'unavailable-units'
          ? `${body.record.quantity} unit(s) marked unavailable. ${body.equipment_type.usable_stock} still usable.`
          : `${body.record.quantity} unit(s) restored. ${body.equipment_type.usable_stock} now usable.`,
      );
    } catch { setError('Could not record that. Try again.'); }
    finally { setSaving(false); }
  }

  if (loadError) return <section className="equipment-unavailability"><p className="error" role="alert">{loadError}</p></section>;
  if (!stock) return <p role="status">Loading unavailable units…</p>;

  return <section className="equipment-unavailability" aria-labelledby="equipment-unavailability-title">
    <header>
      <p className="eyebrow">Technical support · inventory</p>
      <h1 id="equipment-unavailability-title">{stock.name}</h1>
      <p>Record damaged or out-of-service units so they are not offered to other events.</p>
    </header>

    <dl className="equipment-unavailability__figures" aria-label="Stock figures">
      <div><dt>Total stock</dt><dd>{stock.total_stock}</dd></div>
      <div><dt>Unavailable</dt><dd>{stock.unavailable_units}</dd></div>
      <div><dt>Usable</dt><dd data-testid="usable-stock">{stock.usable_stock}</dd></div>
    </dl>

    <form className="equipment-unavailability__form" onSubmit={event => event.preventDefault()}>
      <label htmlFor="unavailable-quantity">Number of units</label>
      <input id="unavailable-quantity" name="quantity" type="number" min={1} value={quantity}
        onChange={event => setQuantity(event.target.value)} />

      <label htmlFor="unavailable-reason">Reason</label>
      <textarea id="unavailable-reason" name="reason" value={reason}
        onChange={event => setReason(event.target.value)} />

      {/* The server's refusal is shown here, beside the fields it is about (TC-SPL-96-08). */}
      {error && <p className="error" role="alert">{error}</p>}
      {confirmation && <p className="notice" role="status">{confirmation}</p>}

      <button type="button" className="button button--primary" disabled={saving}
        onClick={() => { void submit('unavailable-units'); }}>
        {saving ? 'Saving…' : 'Mark unavailable'}
      </button>
      <button type="button" className="button button--secondary" disabled={saving}
        onClick={() => { void submit('restored-units'); }}>
        Restore units
      </button>
    </form>

    <h2>History</h2>
    {history.length === 0
      ? <p>No units have been marked unavailable.</p>
      : <ul className="equipment-unavailability__history">
          {history.map(entry => <li key={entry.id}>
            <span>{entry.action === 'marked_unavailable' ? 'Marked unavailable' : 'Restored'}: {entry.quantity}</span>
            <span>{entry.reason}</span>
            <span>{formatMoment(entry.recorded_at)}</span>
          </li>)}
        </ul>}
  </section>;
}
