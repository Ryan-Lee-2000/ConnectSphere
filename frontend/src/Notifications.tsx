import { useEffect, useState, type MouseEvent } from 'react';
import { defaultRequest, responseError, type ApiRequest } from './api';

type Notice = {
  id: number;
  message: string;
  event: { id: number; name: string };
  // Chosen by the server for the recipient; older payloads may not carry it.
  link?: string;
  created_at: string;
  read: boolean;
};

function formatWhen(value: string) {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
}

const EVENT_LINK =
  /^\/workspace\/(?:(?:assigned|organisation)-events\/\d+|equipment-review-queue|booking-requests|my-registrations)$/;

// The server picks the page for this recipient (SPL-134: organisers have their own event page;
// SPL-122: Technical Support opens its review queue; SPL-104: Venue Staff open the booking queue;
// SPL-124: attendees open My registrations).
// Anything that is not a known event page falls back to the coordinator page, which is what every
// notice opened before the server sent a link.
function eventPath(notice: Notice) {
  return notice.link && EVENT_LINK.test(notice.link)
    ? notice.link
    : `/workspace/assigned-events/${notice.event.id}`;
}

// SPL-101. The signed-in account's own notifications, newest first. The server decides whose
// notices these are; this view never sends an account identifier.
export function Notifications({
  accessToken,
  onNavigate,
  request,
}: {
  accessToken: string;
  onNavigate: (path: string) => void;
  request?: ApiRequest;
}) {
  const [notices, setNotices] = useState<Notice[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const api = request || defaultRequest(accessToken);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await api('/api/notifications');
        const body = await response.json().catch(() => null);
        if (!active) return;
        if (!response.ok || !Array.isArray(body?.notifications)) {
          setError("We couldn't load your notifications. Try again shortly.");
          return;
        }
        setNotices(body.notifications);
        setUnread(body.unread_count);
      } catch {
        if (active) setError("We couldn't load your notifications. Try again shortly.");
      }
    }
    void load();
    return () => { active = false; };
  }, []); // The request function is stable for the life of this workspace view.

  async function markRead(path: string, apply: (notice: Notice) => Notice) {
    setBusy(true);
    setError(null);
    try {
      const response = await api(path, { method: 'POST' });
      if (!response.ok) {
        setError(await responseError(response, "We couldn't update your notifications. Try again."));
        return;
      }
      const body = await response.json();
      setNotices(current => current?.map(apply) ?? current);
      setUnread(body.unread_count);
    } catch {
      setError("We couldn't update your notifications. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function open(click: MouseEvent<HTMLAnchorElement>, notice: Notice) {
    click.preventDefault();
    onNavigate(eventPath(notice));
  }

  if (notices === null && !error) {
    return <section className="notifications" aria-busy="true" aria-live="polite">
      <p className="visually-hidden">Loading notifications</p>
      <div className="notifications__skeleton" />
    </section>;
  }

  return <section className="notifications" aria-labelledby="notifications-title">
    <p className="eyebrow">Your inbox</p>
    <div className="notifications__heading">
      <h2 id="notifications-title">Notifications</h2>
      <div className="notifications__actions">
        {notices !== null && <p className="notifications__count" role="status">
          <strong>{unread}</strong> unread
        </p>}
        {/* SPL-126: email for each notification type is chosen on its own page. */}
        <a
          className="notifications__settings-link"
          href="/workspace/notification-settings"
          onClick={click => { click.preventDefault(); onNavigate('/workspace/notification-settings'); }}
        >Email settings</a>
      </div>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {notices !== null && (notices.length === 0
      ? <div className="notifications__empty" role="status">
        <strong>No notifications yet.</strong>
        <span>Important changes that affect you will appear here.</span>
      </div>
      : <>
        <button
          className="button button--secondary"
          disabled={busy || unread === 0}
          onClick={() => void markRead('/api/notifications/read-all', notice => ({ ...notice, read: true }))}
          type="button"
        >Mark all as read</button>
        <ul className="notifications__list">
          {notices.map(notice => <li
            className={notice.read ? 'notifications__item' : 'notifications__item notifications__item--unread'}
            key={notice.id}
          >
            <div>
              <p className="notifications__message">
                {!notice.read && <span className="visually-hidden">Unread: </span>}
                {notice.message}
              </p>
              <p className="notifications__meta">
                <a
                  href={eventPath(notice)}
                  onClick={click => open(click, notice)}
                >{notice.event.name}</a>
                <span>{formatWhen(notice.created_at)}</span>
              </p>
            </div>
            {!notice.read && <button
              aria-label={`Mark as read: ${notice.message}`}
              className="button button--secondary"
              disabled={busy}
              onClick={() => void markRead(
                `/api/notifications/${notice.id}/read`,
                item => (item.id === notice.id ? { ...item, read: true } : item),
              )}
              type="button"
            >Mark as read</button>}
          </li>)}
        </ul>
      </>)}
  </section>;
}
