import { CircleAlert } from 'lucide-react';
import { useEffect, useState, type MouseEvent } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

type Setting = {
  type: string;
  label: string;
  description: string;
  role: string;
  role_label: string;
  email: boolean;
};

type RowState = { saving: boolean; message: string | null; failed: boolean };

const LOAD_ERROR = "We couldn't load your email settings. Try again shortly.";
const SAVE_ERROR = "We couldn't save that setting. Try again.";

// SPL-126. The signed-in account's email setting for each notification type its roles receive.
// The server decides whose settings these are; this view never sends an account identifier.
export function NotificationSettings({
  accessToken,
  onNavigate,
  request,
}: {
  accessToken: string;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
}) {
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const api = request || defaultRequest(accessToken);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await api('/api/notification-settings');
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok || !Array.isArray(body?.types)) {
          setError(LOAD_ERROR);
          return;
        }
        setSettings(body.types);
      } catch {
        if (active) setError(LOAD_ERROR);
      }
    }
    void load();
    return () => { active = false; };
  }, []); // The request function is stable for the life of this workspace view.

  function setEmail(type: string, email: boolean) {
    setSettings(current => current?.map(item => (item.type === type ? { ...item, email } : item)) ?? current);
  }

  // Each switch saves at once; a failed save puts the switch back and says so.
  async function change(setting: Setting, email: boolean) {
    setEmail(setting.type, email);
    setRows(current => ({ ...current, [setting.type]: { saving: true, message: null, failed: false } }));
    let message = SAVE_ERROR;
    try {
      const response = await api(`/api/notification-settings/${encodeURIComponent(setting.type)}`, {
        method: 'PUT',
        body: JSON.stringify({ email }),
      });
      if (response.ok) {
        setRows(current => ({
          ...current,
          [setting.type]: { saving: false, message: email ? 'Email on' : 'Email off', failed: false },
        }));
        return;
      }
      message = await responseError(response, SAVE_ERROR);
    } catch {
      // Network failure: keep the generic message.
    }
    setEmail(setting.type, !email);
    setRows(current => ({ ...current, [setting.type]: { saving: false, message, failed: true } }));
  }

  function back(click: MouseEvent<HTMLAnchorElement>) {
    click.preventDefault();
    onNavigate('/workspace/notifications');
  }

  if (settings === null && !error) {
    return <section className="notification-settings" aria-busy="true" aria-live="polite">
      <p className="visually-hidden">Loading email settings</p>
      <div className="notifications__skeleton" />
    </section>;
  }

  const groups = (settings ?? []).reduce<{ role: string; label: string; items: Setting[] }[]>((all, item) => {
    const group = all.find(entry => entry.role === item.role);
    if (group) group.items.push(item);
    else all.push({ role: item.role, label: item.role_label, items: [item] });
    return all;
  }, []);

  return <section className="notification-settings" aria-labelledby="notification-settings-title">
    <p className="eyebrow">Your inbox</p>
    <h2 id="notification-settings-title">Email settings</h2>
    <p className="notification-settings__intro">
      Choose which notifications are also sent by email. Every notification still appears in your
      {' '}<a href="/workspace/notifications" onClick={back}>in-app inbox</a>.
    </p>
    {error && <p className="error" role="alert">{error}</p>}
    {settings !== null && (groups.length === 0
      ? <div className="notifications__empty" role="status">
        <strong>No email notifications for your role yet.</strong>
        <span>Notifications for your role will be listed here once they exist.</span>
      </div>
      : groups.map(group => <fieldset className="notification-settings__group" key={group.role}>
        <legend>{group.label}</legend>
        <ul className="notification-settings__list">
          {group.items.map(setting => {
            const row = rows[setting.type];
            const inputId = `email-setting-${setting.type}`;
            return <li className="notification-settings__item" key={setting.type}>
              <div>
                <label className="notification-settings__label" htmlFor={inputId}>{setting.label}</label>
                <p className="notification-settings__description" id={`${inputId}-description`}>
                  {setting.description}
                </p>
              </div>
              <div className="notification-settings__control">
                <input
                  aria-describedby={`${inputId}-description`}
                  checked={setting.email}
                  className="switch"
                  disabled={row?.saving}
                  id={inputId}
                  onChange={event => void change(setting, event.target.checked)}
                  role="switch"
                  type="checkbox"
                />
                <span aria-live="polite" className={row?.failed
                  ? 'notification-settings__status notification-settings__status--error'
                  : 'notification-settings__status'}
                >
                  {row?.failed && <CircleAlert aria-hidden="true" size={16} />}
                  {row?.saving ? 'Saving…' : row?.message ?? (setting.email ? 'Email on' : 'Email off')}
                </span>
              </div>
            </li>;
          })}
        </ul>
      </fieldset>))}
  </section>;
}
