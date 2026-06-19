import { useEffect, useMemo, useState } from 'react';
import { Label } from '../ui/label';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { Separator } from '../ui/separator';
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

  const [gatewayKeys, setGatewayKeys] = useState(appSettings.spam_gateway_keys ?? '');
  const [windowSecs, setWindowSecs] = useState(String(appSettings.spam_live_window_secs ?? 30));
  const [packetThreshold, setPacketThreshold] = useState(
    String(appSettings.spam_live_packet_threshold ?? 15)
  );
  const [clusterMinRatio, setClusterMinRatio] = useState(
    String(appSettings.spam_live_cluster_min_ratio ?? 0.15)
  );
  const [broadcastCooldownSecs, setBroadcastCooldownSecs] = useState(
    String(appSettings.spam_live_broadcast_cooldown_secs ?? 10)
  );
  const [holdSecs, setHoldSecs] = useState(String(appSettings.spam_live_hold_secs ?? 300));
  const [episodeRetentionSecs, setEpisodeRetentionSecs] = useState(
    String(appSettings.spam_live_episode_retention_secs ?? 0)
  );
  const [maxReportClusters, setMaxReportClusters] = useState(
    String(appSettings.spam_live_max_report_clusters ?? 0)
  );
  const [flukeMaxPackets, setFlukeMaxPackets] = useState(
    String(appSettings.spam_live_fluke_max_packets ?? 35)
  );
  const [flukeMaxDurationSecs, setFlukeMaxDurationSecs] = useState(
    String(appSettings.spam_live_fluke_max_duration_secs ?? 300)
  );

  const [enabled, setEnabled] = useState(appSettings.spam_flood_automation_enabled);
  const [selectedKeys, setSelectedKeys] = useState<string[]>(
    appSettings.spam_flood_repeater_keys ?? []
  );
  const [startCommand, setStartCommand] = useState(appSettings.spam_flood_start_command ?? '');
  const [endCommand, setEndCommand] = useState(appSettings.spam_flood_end_command ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setGatewayKeys(appSettings.spam_gateway_keys ?? '');
    setWindowSecs(String(appSettings.spam_live_window_secs ?? 30));
    setPacketThreshold(String(appSettings.spam_live_packet_threshold ?? 15));
    setClusterMinRatio(String(appSettings.spam_live_cluster_min_ratio ?? 0.15));
    setBroadcastCooldownSecs(String(appSettings.spam_live_broadcast_cooldown_secs ?? 10));
    setHoldSecs(String(appSettings.spam_live_hold_secs ?? 300));
    setEpisodeRetentionSecs(String(appSettings.spam_live_episode_retention_secs ?? 0));
    setMaxReportClusters(String(appSettings.spam_live_max_report_clusters ?? 0));
    setFlukeMaxPackets(String(appSettings.spam_live_fluke_max_packets ?? 35));
    setFlukeMaxDurationSecs(String(appSettings.spam_live_fluke_max_duration_secs ?? 300));
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

  const parseBoundedInt = (
    raw: string,
    label: string,
    min: number,
    max: number
  ): number | null => {
    const value = Number.parseInt(raw, 10);
    if (!Number.isFinite(value) || value < min || value > max) {
      toast.error(`${label} must be between ${min} and ${max}`);
      return null;
    }
    return value;
  };

  const handleSave = async () => {
    const parsedWindow = parseBoundedInt(windowSecs, 'Detection window', 5, 300);
    const parsedThreshold = parseBoundedInt(packetThreshold, 'Packet threshold', 5, 1000);
    const parsedCooldown = parseBoundedInt(broadcastCooldownSecs, 'Broadcast cooldown', 1, 120);
    const parsedHold = parseBoundedInt(holdSecs, 'Hold window', 0, 3600);
    const parsedRetention = parseBoundedInt(episodeRetentionSecs, 'Episode retention', 0, 3600);
    const parsedMaxClusters = parseBoundedInt(maxReportClusters, 'Max report clusters', 0, 100);
    const parsedFlukeMaxPackets = parseBoundedInt(
      flukeMaxPackets,
      'Fluke history packet cap',
      0,
      1000
    );
    const parsedFlukeMaxDuration = parseBoundedInt(
      flukeMaxDurationSecs,
      'Fluke history duration',
      0,
      3600
    );
    const parsedRatio = Number.parseFloat(clusterMinRatio);
    if (
      parsedWindow === null ||
      parsedThreshold === null ||
      parsedCooldown === null ||
      parsedHold === null ||
      parsedRetention === null ||
      parsedMaxClusters === null ||
      parsedFlukeMaxPackets === null ||
      parsedFlukeMaxDuration === null
    ) {
      return;
    }
    if (!Number.isFinite(parsedRatio) || parsedRatio < 0.05 || parsedRatio > 1) {
      toast.error('Cluster min ratio must be between 0.05 and 1.0');
      return;
    }

    setSaving(true);
    try {
      await onSaveAppSettings({
        spam_gateway_keys: gatewayKeys.trim(),
        spam_live_window_secs: parsedWindow,
        spam_live_packet_threshold: parsedThreshold,
        spam_live_cluster_min_ratio: parsedRatio,
        spam_live_broadcast_cooldown_secs: parsedCooldown,
        spam_live_hold_secs: parsedHold,
        spam_live_episode_retention_secs: parsedRetention,
        spam_live_max_report_clusters: parsedMaxClusters,
        spam_live_fluke_max_packets: parsedFlukeMaxPackets,
        spam_live_fluke_max_duration_secs: parsedFlukeMaxDuration,
        spam_flood_automation_enabled: enabled,
        spam_flood_repeater_keys: selectedKeys,
        spam_flood_start_command: startCommand.trim(),
        spam_flood_end_command: endCommand.trim(),
      });
      toast.success('Spam defense settings saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save spam defense settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={className}>
      <div className="space-y-6">
        <div>
          <h3 className="text-base font-semibold tracking-tight">Live Flood Detection</h3>
          <p className="mt-1 text-[0.8125rem] text-muted-foreground">
            Tune how aggressively RemoteTerm detects and reports DM flood episodes. Changes apply
            immediately without restarting the server.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="spam-gateway-keys">Gateway repeater keys</Label>
          <textarea
            id="spam-gateway-keys"
            value={gatewayKeys}
            onChange={(event) => setGatewayKeys(event.target.value)}
            placeholder="Leave empty for built-in GWNL defaults, or none to disable stripping"
            rows={3}
            className="flex min-h-[4.5rem] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <p className="text-[0.8125rem] text-muted-foreground">
            Comma-separated full public keys for internet/MQTT gateway repeaters stripped from RF
            paths before clustering.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="spam-window-secs">Detection window (seconds)</Label>
            <Input
              id="spam-window-secs"
              type="number"
              min={5}
              max={300}
              value={windowSecs}
              onChange={(event) => setWindowSecs(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-packet-threshold">Packet threshold</Label>
            <Input
              id="spam-packet-threshold"
              type="number"
              min={5}
              max={1000}
              value={packetThreshold}
              onChange={(event) => setPacketThreshold(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-cluster-min-ratio">Cluster min ratio</Label>
            <Input
              id="spam-cluster-min-ratio"
              type="number"
              min={0.05}
              max={1}
              step={0.01}
              value={clusterMinRatio}
              onChange={(event) => setClusterMinRatio(event.target.value)}
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              Minimum share of flood packets for a hotspot candidate (0.15 = 15%).
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-broadcast-cooldown">Broadcast cooldown (seconds)</Label>
            <Input
              id="spam-broadcast-cooldown"
              type="number"
              min={1}
              max={120}
              value={broadcastCooldownSecs}
              onChange={(event) => setBroadcastCooldownSecs(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-hold-secs">Hold window (seconds)</Label>
            <Input
              id="spam-hold-secs"
              type="number"
              min={0}
              max={3600}
              value={holdSecs}
              onChange={(event) => setHoldSecs(event.target.value)}
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              Keep flood alarms active this long after the last above-threshold observation.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="spam-episode-retention">Episode retention (seconds)</Label>
            <Input
              id="spam-episode-retention"
              type="number"
              min={0}
              max={3600}
              value={episodeRetentionSecs}
              onChange={(event) => setEpisodeRetentionSecs(event.target.value)}
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              0 matches the hold window (recommended).
            </p>
          </div>
          <div className="space-y-2 md:col-span-2">
            <Label htmlFor="spam-max-report-clusters">Max report clusters</Label>
            <Input
              id="spam-max-report-clusters"
              type="number"
              min={0}
              max={100}
              value={maxReportClusters}
              onChange={(event) => setMaxReportClusters(event.target.value)}
              className="md:max-w-xs"
            />
            <p className="text-[0.8125rem] text-muted-foreground">
              Maximum hotspot candidates shown in live UI and history. 0 means unlimited.
            </p>
          </div>
        </div>

        <div className="space-y-3 rounded-md border border-border bg-muted/10 p-3">
          <div>
            <h4 className="text-sm font-semibold">Fluke history filter</h4>
            <p className="mt-1 text-[0.8125rem] text-muted-foreground">
              Live flood alarms still fire on short bursts. When an episode ends, it is dropped from
              Flood Alert History if it stayed below the packet cap and ended within the duration
              window.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="spam-fluke-max-packets">History packet cap</Label>
              <Input
                id="spam-fluke-max-packets"
                type="number"
                min={0}
                max={1000}
                value={flukeMaxPackets}
                onChange={(event) => setFlukeMaxPackets(event.target.value)}
              />
              <p className="text-[0.8125rem] text-muted-foreground">
                Episodes with fewer total DM paths are not saved to history. 0 disables this filter.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="spam-fluke-max-duration">History duration window (seconds)</Label>
              <Input
                id="spam-fluke-max-duration"
                type="number"
                min={0}
                max={3600}
                value={flukeMaxDurationSecs}
                onChange={(event) => setFlukeMaxDurationSecs(event.target.value)}
              />
              <p className="text-[0.8125rem] text-muted-foreground">
                Only episodes ending within this window can be discarded (default 300 = 5 minutes).
              </p>
            </div>
          </div>
        </div>

        <Separator />

        <div>
          <h3 className="text-base font-semibold tracking-tight">Spam Flood Repeater Commands</h3>
          <p className="mt-1 text-[0.8125rem] text-muted-foreground">
            When the live spam tracker starts a flood episode, RemoteTerm sends the configured CLI
            command to selected favorite repeaters twice (5 seconds apart) so a lost packet in
            flood traffic is less likely to block the command. When the episode ends (including the
            post-flood hold window), it sends the restore command the same way. Your radio node must be connected and each repeater must
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
            <div className="max-h-[11.5rem] overflow-y-auto rounded-md border border-border p-3">
              <div className="space-y-2">
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
                        <span className="block text-sm">
                          {contact.name ?? contact.public_key.slice(0, 12)}
                        </span>
                        <span className="block font-mono text-[0.625rem] text-muted-foreground">
                          {contact.public_key.slice(0, 12)}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
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
