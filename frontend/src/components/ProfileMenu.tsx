import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useData } from "../DataContext";
import type { Profile } from "../types";
import { Modal } from "./common";

const COLOURS = ["#39d0a0", "#2563eb", "#e11d48", "#f59e0b", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"];

export function ProfileDot({ colour }: { colour: string }) {
  return <span className="profile-dot" style={{ background: colour }} aria-hidden="true" />;
}

/** "Adding to: ● Name", so a trade is never entered under the wrong person. */
export function ProfileLine({ label = "Adding to" }: { label?: string }) {
  const { activeProfile } = useData();
  if (!activeProfile) return null;
  return (
    <p className="profile-line" data-testid="profile-line">
      {label}: <ProfileDot colour={activeProfile.colour} /> <b>{activeProfile.name}</b>
    </p>
  );
}

function AddProfileDialog({ onClose }: { onClose: () => void }) {
  const { profiles, reloadProfiles, switchProfile, addNotices } = useData();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [colour, setColour] = useState(COLOURS[(profiles.length + 1) % COLOURS.length]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const clean = name.trim().replace(/\s+/g, " ");
  const taken = profiles.some((p) => p.name.toLowerCase() === clean.toLowerCase());

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!clean || taken) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.createProfile({ name: clean, colour });
      await reloadProfiles();
      addNotices(result.warnings);
      switchProfile(result.profile.id);
      navigate("/");
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not create the profile.");
      setSaving(false);
    }
  }

  return (
    <Modal title="Add new profile" onClose={onClose}>
      <form onSubmit={(event) => void save(event)}>
        <label>Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} autoFocus required />
        </label>
        {taken && <p className="form-error" role="alert">A profile named {clean} already exists.</p>}
        <fieldset className="swatches">
          <legend>Colour</legend>
          {COLOURS.map((option) => (
            <button
              key={option} type="button" className={`swatch ${option === colour ? "selected" : ""}`}
              style={{ background: option }} aria-label={`Colour ${option}`} aria-pressed={option === colour}
              onClick={() => setColour(option)}
            />
          ))}
          <input type="color" value={colour} onChange={(e) => setColour(e.target.value)} aria-label="Custom colour" />
        </fieldset>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={saving || !clean || taken}>
            {saving ? "Creating…" : "Create profile"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function DeleteProfileDialog({ profile, onClose }: { profile: Profile; onClose: () => void }) {
  const { profiles, reloadProfiles, switchProfile, addNotices } = useData();
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  const [count, setCount] = useState<number>(profile.transaction_count);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Fresh count, in case trades were added since the list was loaded.
  useEffect(() => {
    reloadProfiles()
      .then((list) => {
        const latest = list.find((p) => p.id === profile.id);
        if (latest) setCount(latest.transaction_count);
      })
      .catch(() => undefined);
  }, [profile.id, reloadProfiles]);

  async function remove(event: FormEvent) {
    event.preventDefault();
    if (typed !== profile.name) return;
    setDeleting(true);
    setError(null);
    try {
      const result = await api.deleteProfile(profile.id);
      const fallback = profiles.find((p) => p.is_default);
      if (fallback) switchProfile(fallback.id);
      await reloadProfiles();
      addNotices([
        `Deleted profile ${profile.name} and ${result.transactions_removed} transaction(s). `
          + `Backup saved to ${result.profile_backup}`,
        ...result.warnings,
      ]);
      navigate("/");
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not delete the profile.");
      setDeleting(false);
    }
  }

  return (
    <Modal title={`Delete profile ${profile.name}?`} onClose={onClose}>
      <form onSubmit={(event) => void remove(event)}>
        <p data-testid="delete-count">
          <b>{count} transaction{count === 1 ? "" : "s"}</b> will be removed.
        </p>
        <p className="muted">
          A backup file with this profile and all its transactions is saved to
          data\backups\profiles\ first. Instruments and prices are shared and stay.
        </p>
        <label><span>Type <b>{profile.name}</b> to confirm</span>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus autoComplete="off" />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="button ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="button danger" disabled={deleting || typed !== profile.name}>
            {deleting ? "Deleting…" : "Delete profile"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ProfileMenu() {
  const { profiles, activeProfile, switchProfile } = useData();
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState<"add" | "delete" | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!activeProfile) return null;
  const isDefault = activeProfile.is_default;

  return (
    <div className="profile-menu" ref={ref}>
      <button
        className="profile-trigger" aria-haspopup="menu" aria-expanded={open}
        data-testid="profile-trigger" onClick={() => setOpen((value) => !value)}
      >
        <ProfileDot colour={activeProfile.colour} />
        <span className="profile-name">{activeProfile.name}</span>
        <span aria-hidden="true" className="caret">▾</span>
      </button>
      {open && (
        <div className="profile-dropdown" role="menu">
          {profiles.map((profile) => (
            <button
              key={profile.id} role="menuitemradio" aria-checked={profile.id === activeProfile.id}
              className={`profile-item ${profile.id === activeProfile.id ? "active" : ""}`}
              onClick={() => {
                switchProfile(profile.id);
                setOpen(false);
              }}
            >
              <ProfileDot colour={profile.colour} />
              <span className="profile-name">{profile.name}</span>
              {profile.is_default && <span className="badge default-tag">default</span>}
              {profile.id === activeProfile.id && <span aria-hidden="true" className="check">✓</span>}
            </button>
          ))}
          <div className="menu-divider" role="separator" />
          <button role="menuitem" className="profile-item" onClick={() => { setOpen(false); setDialog("add"); }}>
            + Add new profile
          </button>
          <button
            role="menuitem"
            className={`profile-item danger-text ${isDefault ? "disabled" : ""}`}
            aria-disabled={isDefault}
            title={isDefault ? "Your default profile can't be deleted" : `Delete ${activeProfile.name}`}
            onClick={() => {
              if (isDefault) return;
              setOpen(false);
              setDialog("delete");
            }}
          >
            Delete current profile
          </button>
        </div>
      )}
      {dialog === "add" && <AddProfileDialog onClose={() => setDialog(null)} />}
      {dialog === "delete" && !isDefault && (
        <DeleteProfileDialog profile={activeProfile} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
