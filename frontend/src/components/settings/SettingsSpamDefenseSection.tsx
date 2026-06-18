import { useEffect, useMemo, useState } from 'react';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { toast } from '../ui/sonner';
import type { AppSettings, AppSettingsUpdate, Contact } from '../../types';

const CONTACT_TYPE_REPEATER = 2;

export function SettingsSpamDefenseSection({
  appSettings,
  onSaveAppSettings,
  contacts = [],
  className,
}: {
  appSettings: AppSettings;
  onSaveAppSettings: (update: AppSettingsUpdate) => Promise<void>;
  contacts?: Contact[];
  className?: string;
}) {
  const favoriteRepeaters = useMemo(
    () =>
      contacts.filter(
        (contact) => contact.favorite && contact.type === CONTACT_TYPE_REPEATER
      ),
    [contacts]
  );

  const [enabled, setEnabled] = useState(appSettings.spam_flood_automation_enabled);
  const [selectedKeys, setSelectedKeys] = useState<string[]>(
    appSettings.spam_flood_repeater_keys ?? []
  );
  const [startCommand, setStartCommand] = useState(appSettings.spam_flood_start_command ?? '');
  const [endCommand, setEndCommand] = useState(appSettings.spam_flood_end_command ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEnabled(appSettings.spam_flood_automation_enabled);
    setSelectedKeys(appSettings.spam_flood_repeater_keys ?? []);
    setStartCommand(appSettings.spam_flood_start_command ?? '');
    setEndCommand(appSettings.spam_flood_end_command ?? '');
  }, [appSettings]);

  const toggleRepeater = (publicKey: string) => {
    setSelectedKeys((current) =>
      current.includes(publicKey)
        ? current.filter((key) => key !== publicKey)
        : [...current, publicKey]
    );
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSaveAppSettings({
        spam_flood_automation_enabled: enabled,
        spam_flood_repeater_keys: selectedKeys,
        spam_flood_start_command: startCommand.trim(),
        spam_flood_end_command: endCommand.trim(),
      });
      toast.success('Spam defense automation saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save spam defense settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={className}>
      <div className="space-y-4">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Spam Flood Repeater Commands</h3>
          <p className="mt-1 text-[0.8125rem] text-muted-foreground">
            When the live spam tracker starts a flood episode, RemoteTerm can send a CLI command to
            selected favorite repeaters. When the episode ends (including the post-flood hold window),
            it sends the restore command. Your radio node must be connected and each repeater must
            accept your CLI access — you need to be on that repeater&apos;s ACL with sufficient
            permission (typically read-write or admin). Log in from the repeater dashboard first if
            privileged commands are required.
          </p>
        </div>

        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-input accent-primary"
          />
          <span className="text-sm">Enable spam-flood repeater automation</span>
        </label>

        <div className="space-y-2">
          <Label className="text-sm font-semibold">Favorite repeaters</Label>
          {favoriteRepeaters.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              No favorite repeaters yet. Star a repeater from its dashboard or chat header, then
              return here to select it.
            </p>
          ) : (
            <div className="space-y-2 rounded-md border border-border p-3">
              {favoriteRepeaters.map((contact) => {
                const checked = selectedKeys.includes(contact.public_key);
                return (
                  <label
                    key={contact.public_key}
                    className="flex items-start gap-2 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleRepeater(contact.public_key)}
                      className="mt-0.5 h-4 w-4 rounded border-input accent-primary"
                    />
                    <span className="min-w-0">
                      <span className="block text-sm">{contact.name ?? contact.public_key.slice(0, 12)}</span>
                      <span className="block font-mono text-[0.625rem] text-muted-foreground">
                        {contact.public_key.slice(0, 12)}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="spam-flood-start-command">Flood start command</Label>
            <Input
              id="spam-flood-start-command"
              value={startCommand}
              onChange={(event) => setStartCommand(event.target.value)}
              placeholder="set repeat off"
              className="font-mono text-sm"
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              Sent once when a spam flood episode begins.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-flood-end-command">Flood end command</Label>
            <Input
              id="spam-flood-end-command"
              value={endCommand}
              onChange={(event) => setEndCommand(event.target.value)}
              placeholder="set repeat on"
              className="font-mono text-sm"
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              Sent once when the episode ends, after the hold window closes.
            </p>
          </div>
        </div>

        <Button type="button" onClick={() => void handleSave()} disabled={saving}>
          {saving ? 'Saving…' : 'Save spam defense settings'}
        </Button>
      </div>
    </div>
  );
}
