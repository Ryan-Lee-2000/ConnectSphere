import { FormEvent, useEffect, useState } from 'react';
import { Boxes, MapPin, Package, Pencil, Plus } from 'lucide-react';
import { defaultRequest, responseError, type ApiRequest } from './api';

export type EquipmentType = {
  id: number;
  name: string;
  description: string | null;
  location: string | null;
  total_stock: number;
};

type Draft = { name: string; description: string; location: string; totalStock: string };
const blankDraft = (): Draft => ({ name: '', description: '', location: '', totalStock: '0' });

export function EquipmentCatalogue({ accessToken, request }: { accessToken: string | null; request?: ApiRequest }) {
  const api = request || (accessToken ? defaultRequest(accessToken) : undefined);
  const [items, setItems] = useState<EquipmentType[]>([]);
  const [draft, setDraft] = useState<Draft>(blankDraft);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(Boolean(api));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    if (!api) return;
    setLoading(true);
    const response = await api('/api/equipment-types');
    if (!response.ok) {
      setError(await responseError(response, 'The equipment catalogue could not be loaded.'));
      setLoading(false);
      return;
    }
    const body = await response.json() as { equipment_types: EquipmentType[] };
    setItems(body.equipment_types);
    setLoading(false);
  };

  useEffect(() => { void load(); }, [accessToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = (field: keyof Draft, value: string) => setDraft(current => ({ ...current, [field]: value }));
  const startEdit = (item: EquipmentType) => {
    setEditingId(item.id);
    setDraft({
      name: item.name,
      description: item.description || '',
      location: item.location || '',
      totalStock: String(item.total_stock),
    });
    setError(null);
    setNotice(null);
  };
  const cancel = () => { setEditingId(null); setDraft(blankDraft()); setError(null); };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api || !Number.isInteger(Number(draft.totalStock)) || Number(draft.totalStock) < 0) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    const response = await api(
      editingId === null ? '/api/equipment-types' : `/api/equipment-types/${editingId}`,
      {
        method: editingId === null ? 'POST' : 'PATCH',
        body: JSON.stringify({
          name: draft.name,
          description: draft.description || null,
          location: draft.location || null,
          total_stock: Number(draft.totalStock),
        }),
      },
    );
    setSaving(false);
    if (!response.ok) {
      setError(await responseError(response, 'The equipment type could not be saved.'));
      return;
    }
    setNotice(editingId === null ? 'Equipment type added to the catalogue.' : 'Equipment type updated.');
    cancel();
    await load();
  }

  return <section className="catalogue" aria-labelledby="equipment-catalogue-heading">
    <div className="catalogue-header">
      <div>
        <p className="eyebrow">Technical support</p>
        <h2 id="equipment-catalogue-heading">Equipment catalogue</h2>
        <p className="catalogue-subtitle">Maintain the shared stock list used when organisers and coordinators record equipment needs.</p>
      </div>
      <Boxes aria-hidden="true" size={32} />
    </div>
    <div className="catalogue-intro"><div><span className="catalogue-kicker">Pooled stock</span><p>Each equipment type represents one shared inventory pool.</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    <form className="venue-form equipment-catalogue__form" onSubmit={submit}>
      <div className="detail-heading"><div><h3>{editingId === null ? 'Add equipment type' : 'Edit equipment type'}</h3><p className="hint">Names are unique regardless of letter case.</p></div></div>
      <div className="equipment-catalogue__form-grid">
        <label>Equipment type name<input required value={draft.name} onChange={event => update('name', event.target.value)} /></label>
        <label>Total units in stock<input min="0" required step="1" type="number" value={draft.totalStock} onChange={event => update('totalStock', event.target.value)} /></label>
        <label className="equipment-catalogue__form-wide">Description<textarea value={draft.description} onChange={event => update('description', event.target.value)} rows={2} /></label>
        <label className="equipment-catalogue__form-wide">Storage location<input value={draft.location} onChange={event => update('location', event.target.value)} /></label>
      </div>
      <div className="form-actions"><button className="button button--primary" disabled={saving} type="submit">{saving ? 'Saving…' : editingId === null ? 'Add equipment type' : 'Save changes'}</button>{editingId !== null && <button className="button button--secondary" onClick={cancel} type="button">Cancel</button>}</div>
    </form>
    <div className="equipment-catalogue__grid" aria-busy={loading}>
      {items.map(item => <article className="equipment-card" key={item.id}>
        <div className="equipment-card__topline">
          <span className="equipment-card__icon" aria-hidden="true"><Package size={18} /></span>
          <span className="equipment-card__stock"><strong>{item.total_stock}</strong> units in stock</span>
        </div>
        <div className="equipment-card__heading"><div><p className="venue-card-label">Equipment type</p><h3>{item.name}</h3></div><button className="icon-button" aria-label={`Edit ${item.name}`} onClick={() => startEdit(item)} type="button"><Pencil size={16} />Edit</button></div>
        <p className="equipment-card__description">{item.description || 'No description recorded.'}</p>
        <div className="equipment-card__location"><MapPin size={16} aria-hidden="true" /><span>{item.location || 'Storage location not recorded'}</span></div>
      </article>)}
      {!loading && items.length === 0 && <div className="catalogue-empty"><Plus aria-hidden="true" size={22} /><h3>No equipment types yet</h3><p>Add the first shared equipment type above.</p></div>}
    </div>
  </section>;
}
