import { useState } from 'react';
import { Alert, Text, View } from 'react-native';

import {
  Body,
  Button,
  Card,
  Chips,
  Divider,
  ErrorBanner,
  Field,
  H2,
  KV,
  Label,
  Loading,
  Notice,
  Row,
  Screen,
  Segmented,
  Stepper,
  Toggle,
} from '../../components/ui';
import { api } from '../../lib/api';
import { money, usd } from '../../lib/format';
import { useSession } from '../../lib/session';
import { colors, space } from '../../lib/theme';
import type { ModelInfo, Preset, Settings, SettingsResponse, Usage } from '../../lib/types';
import { useApi } from '../../lib/useApi';

const ANALYSTS = [
  { label: 'Market', value: 'market' },
  { label: 'Sentiment', value: 'social' },
  { label: 'News', value: 'news' },
  { label: 'Fundamentals', value: 'fundamentals' },
];

export default function SettingsScreen() {
  const { connection, disconnect } = useSession();
  const data = useApi(async () => {
    const [s, m, u] = await Promise.all([api.settings(), api.models(), api.usage()]);
    return { s, models: m.models, presets: m.presets, efforts: m.efforts, usage: u };
  });
  // Edits update this local copy; a pull-to-refresh drops it for the server's.
  const [local, setResp] = useState<SettingsResponse | null>(null);
  const resp = local ?? data.data?.s ?? null;
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  if (!resp || !data.data) return data.error ? <Screen><ErrorBanner message={data.error} /></Screen> : <Loading />;
  const s = resp.settings;

  const update = async (patch: Partial<Settings> | Record<string, unknown>, note = 'Saved') => {
    setError(null);
    try {
      const r = await api.updateSettings(patch);
      setResp((prev) => (prev ? { ...prev, ...r } : r));
      setSaved(note);
      setTimeout(() => setSaved(null), 1500);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Screen
      refreshing={data.refreshing}
      onRefresh={() => {
        setResp(null);
        data.reload();
      }}
    >
      {saved ? <Notice color={colors.up}>{saved}</Notice> : null}
      <ErrorBanner message={error} />

      <KeysCard resp={resp} onKeys={(keys) => setResp({ ...resp, keys })} />
      <UsageCard usage={data.data.usage} budget={s.monthly_budget_usd} onBudget={(v) => update({ monthly_budget_usd: v })} />
      <ModelsCard
        s={s}
        models={data.data.models}
        presets={data.data.presets}
        efforts={data.data.efforts}
        update={update}
      />

      <Card>
        <H2>Agent team defaults</H2>
        <Body muted style={{ fontSize: 13, marginBottom: space.md }}>
          Used by every new analysis and by autopilot. You can still change them per run.
        </Body>
        <Label style={{ marginBottom: 8 }}>Analysts</Label>
        <Chips
          options={ANALYSTS}
          selected={s.analysts}
          onToggle={(v) =>
            update({ analysts: s.analysts.includes(v) ? s.analysts.filter((a) => a !== v) : [...s.analysts, v] })
          }
        />
        <View style={{ marginTop: space.md }}>
          <Stepper
            label="Bull vs bear debate rounds"
            value={s.max_debate_rounds}
            min={1}
            max={5}
            onChange={(v) => update({ max_debate_rounds: v })}
          />
          <Stepper
            label="Risk debate rounds"
            value={s.max_risk_rounds}
            min={1}
            max={5}
            onChange={(v) => update({ max_risk_rounds: v })}
          />
        </View>
        <Toggle
          label="Tell the agents what I hold"
          hint="The trader, risk team and portfolio manager see your paper cash and positions."
          value={s.share_portfolio}
          onChange={(v) => update({ share_portfolio: v })}
        />
        <TextSetting
          label="Report language"
          value={s.output_language}
          onSave={(v) => update({ output_language: v || 'English' })}
        />
      </Card>

      <Card>
        <H2>Turning decisions into trades</H2>
        <Body muted style={{ fontSize: 13, marginBottom: space.sm }}>
          Buy grows a position to the maximum, Overweight to part of it, Underweight trims, Sell closes. Hold does
          nothing. The account never shorts.
        </Body>
        <Toggle
          label="Auto-execute new analyses"
          hint="Default for runs you start. Autopilot has its own switch below."
          value={s.auto_execute}
          onChange={(v) => update({ auto_execute: v })}
        />
        <Stepper
          label="Max position size"
          value={s.max_position_pct}
          min={1}
          max={100}
          step={1}
          format={(v) => `${v}%`}
          onChange={(v) => update({ max_position_pct: v })}
        />
        <Stepper
          label="Overweight = share of max"
          value={Math.round(s.overweight_fraction * 100)}
          min={10}
          max={100}
          step={10}
          format={(v) => `${v}%`}
          onChange={(v) => update({ overweight_fraction: v / 100 })}
        />
        <Stepper
          label="Underweight trims"
          value={Math.round(s.underweight_trim * 100)}
          min={10}
          max={100}
          step={10}
          format={(v) => `${v}%`}
          onChange={(v) => update({ underweight_trim: v / 100 })}
        />
        <Toggle
          label="Place the trader's stop-loss"
          value={s.use_stop_loss}
          onChange={(v) => update({ use_stop_loss: v })}
        />
        <Toggle
          label="Take profit at the price target"
          value={s.use_take_profit}
          onChange={(v) => update({ use_take_profit: v })}
        />
        <Toggle
          label="Fractional shares"
          value={s.allow_fractional}
          onChange={(v) => update({ allow_fractional: v })}
        />
        <Divider />
        <Label style={{ marginVertical: 8 }}>Simulated costs</Label>
        <Stepper
          label="Slippage"
          value={s.slippage_bps}
          min={0}
          max={100}
          step={1}
          format={(v) => `${v} bps`}
          onChange={(v) => update({ slippage_bps: v })}
        />
        <Stepper
          label="Commission per trade"
          value={s.commission_per_trade}
          min={0}
          max={20}
          step={0.5}
          format={(v) => money(v)}
          onChange={(v) => update({ commission_per_trade: v })}
        />
        <Stepper
          label="Commission"
          value={s.commission_bps}
          min={0}
          max={100}
          step={1}
          format={(v) => `${v} bps`}
          onChange={(v) => update({ commission_bps: v })}
        />
      </Card>

      <AutopilotCard s={s} message={resp.autopilot_message} update={update} />
      <AccountCard />

      <Card>
        <H2>Server</H2>
        <KV k="Connected to" v={connection?.url ?? '—'} />
        <Stepper
          label="Analyses at once (needs server restart)"
          value={s.max_concurrent_runs}
          min={1}
          max={4}
          onChange={(v) => update({ max_concurrent_runs: v })}
        />
        <Stepper
          label="Check waiting orders every"
          value={s.order_check_seconds}
          min={15}
          max={600}
          step={15}
          format={(v) => `${v}s`}
          onChange={(v) => update({ order_check_seconds: v })}
        />
        <Button title="Disconnect" kind="secondary" onPress={disconnect} style={{ marginTop: space.md }} />
      </Card>

      <Body muted style={{ fontSize: 12, textAlign: 'center' }}>
        Built on TradingAgents (Tauric Research), a research framework. Simulated trading for learning only; not
        financial advice.
      </Body>
    </Screen>
  );
}

function TextSetting({ label, value, onSave, hint }: { label: string; value: string; onSave: (v: string) => void; hint?: string }) {
  const [v, setV] = useState(value);
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    setV(value);
  }
  return (
    <Field
      label={label}
      value={v}
      onChangeText={setV}
      onEndEditing={() => v !== value && onSave(v.trim())}
      hint={hint}
    />
  );
}

function KeysCard({ resp, onKeys }: { resp: SettingsResponse; onKeys: (k: SettingsResponse['keys']) => void }) {
  const [key, setKey] = useState('');
  const [fred, setFred] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const a = resp.keys.anthropic;

  const save = async (name: 'anthropic' | 'fred', value: string | null) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.setKey(name, value);
      onKeys(r.keys);
      if (name === 'anthropic' && value) {
        const t = await api.testKey();
        setMsg({ ok: t.ok, text: t.message });
      } else {
        setMsg({ ok: true, text: value ? 'Saved' : 'Removed' });
      }
      setKey('');
      setFred('');
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card style={!a.set ? { borderColor: colors.warn } : undefined}>
      <H2>Anthropic API key</H2>
      <Body muted style={{ fontSize: 13, marginBottom: space.md }}>
        Every agent runs on Claude through your key. It is sent once to your server and stored there (never shown
        again in full). Create one at console.anthropic.com.
      </Body>
      <KV k="Status" v={a.set ? `Saved (${a.preview})` : 'Not set'} color={a.set ? colors.up : colors.warn} />
      <Field
        value={key}
        onChangeText={setKey}
        placeholder="sk-ant-…"
        autoCapitalize="none"
        secureTextEntry
        style={{ marginTop: space.sm }}
      />
      <Row style={{ gap: space.sm }}>
        <Button title="Save & test" onPress={() => save('anthropic', key.trim())} disabled={!key.trim()} loading={busy} style={{ flex: 1 }} />
        {a.set && (
          <Button
            title="Test"
            kind="secondary"
            onPress={async () => {
              setMsg(null);
              const t = await api.testKey().catch((e) => ({ ok: false, message: (e as Error).message }));
              setMsg({ ok: t.ok, text: t.message });
            }}
          />
        )}
        {a.set && (
          <Button
            title="Remove"
            kind="danger"
            onPress={() =>
              Alert.alert('Remove the API key?', 'The agents cannot run until you add one again.', [
                { text: 'Cancel', style: 'cancel' },
                { text: 'Remove', style: 'destructive', onPress: () => save('anthropic', null) },
              ])
            }
          />
        )}
      </Row>
      {msg ? (
        <Text style={{ color: msg.ok ? colors.up : colors.down, marginTop: space.sm }}>{msg.text}</Text>
      ) : null}
      <Divider />
      <Label style={{ marginVertical: 6 }}>Optional: FRED key (free macro data for the news analyst)</Label>
      <KV k="FRED" v={resp.keys.fred.set ? `Saved (${resp.keys.fred.preview})` : 'Not set'} />
      <Row style={{ gap: space.sm }}>
        <Field value={fred} onChangeText={setFred} placeholder="FRED API key" autoCapitalize="none" style={{ flex: 1, marginBottom: 0 }} />
        <Button title="Save" kind="secondary" onPress={() => save('fred', fred.trim() || null)} />
      </Row>
    </Card>
  );
}

function UsageCard({ usage, budget, onBudget }: { usage: Usage; budget: number | null; onBudget: (v: number | null) => void }) {
  const [b, setB] = useState(budget != null ? String(budget) : '');
  const used = budget ? Math.min(1, usage.month_cost_usd / budget) : 0;
  return (
    <Card>
      <H2>Claude usage</H2>
      <Body muted style={{ fontSize: 13, marginBottom: space.sm }}>
        Estimated from token counts at list prices. Your Anthropic Console has the exact bill.
      </Body>
      <KV k="This month" v={usd(usage.month_cost_usd)} />
      {budget ? (
        <View style={{ height: 6, backgroundColor: colors.surfaceAlt, borderRadius: 3, marginVertical: 6 }}>
          <View
            style={{
              height: 6,
              borderRadius: 3,
              width: `${used * 100}%`,
              backgroundColor: used > 0.9 ? colors.down : used > 0.7 ? colors.warn : colors.accent,
            }}
          />
        </View>
      ) : null}
      <KV k="Average analysis" v={usage.avg_run_cost_usd != null ? usd(usage.avg_run_cost_usd) : 'no runs yet'} />
      <KV k="All time" v={usd(usage.all_time_cost_usd)} />
      {usage.by_model.map((m) => (
        <KV key={m.model} k={`  ${m.model}`} v={usd(m.cost_usd)} />
      ))}
      <Field
        style={{ marginTop: space.md }}
        label="Monthly budget (USD)"
        value={b}
        onChangeText={setB}
        keyboardType="decimal-pad"
        placeholder="no limit"
        onEndEditing={() => onBudget(b.trim() ? Number(b) : null)}
        hint="New analyses, replays and chats are refused once this month's estimate reaches it. Leave empty for no limit."
      />
    </Card>
  );
}

function ModelsCard({
  s,
  models,
  presets,
  efforts,
  update,
}: {
  s: Settings;
  models: ModelInfo[];
  presets: Preset[];
  efforts: string[];
  update: (p: Partial<Settings>, note?: string) => void;
}) {
  const active = presets.find((p) => p.quick_model === s.quick_model && p.deep_model === s.deep_model);
  const opts = models.map((m) => ({ label: m.id.replace('claude-', ''), value: m.id }));
  const priceOf = (id: string) => {
    const m = models.find((x) => x.id === id);
    return m ? `$${m.input_per_mtok} in / $${m.output_per_mtok} out per million tokens` : 'custom model';
  };
  return (
    <Card>
      <H2>Claude models</H2>
      <Body muted style={{ fontSize: 13, marginBottom: space.md }}>
        The quick tier runs the analysts, researchers, trader and risk debaters (most of the calls). The deep tier
        runs the research and portfolio managers, who make the decisions.
      </Body>
      <Label style={{ marginBottom: 8 }}>Presets</Label>
      <Chips
        options={presets.map((p) => ({ label: p.label, value: p.id }))}
        selected={active ? [active.id] : []}
        onToggle={(id) => {
          const p = presets.find((x) => x.id === id);
          if (p) update({ quick_model: p.quick_model, deep_model: p.deep_model }, `Preset: ${p.label}`);
        }}
      />
      {active ? <Body muted style={{ fontSize: 12, marginTop: 6 }}>{active.description}</Body> : null}

      <Label style={{ marginTop: space.lg, marginBottom: 8 }}>Quick tier: {s.quick_model}</Label>
      <Chips options={opts} selected={[s.quick_model]} onToggle={(v) => update({ quick_model: v })} />
      <Body muted style={{ fontSize: 12, marginTop: 4 }}>{priceOf(s.quick_model)}</Body>

      <Label style={{ marginTop: space.lg, marginBottom: 8 }}>Deep tier: {s.deep_model}</Label>
      <Chips options={opts} selected={[s.deep_model]} onToggle={(v) => update({ deep_model: v })} />
      <Body muted style={{ fontSize: 12, marginTop: 4 }}>{priceOf(s.deep_model)}</Body>

      <Label style={{ marginTop: space.lg, marginBottom: 8 }}>Thinking effort</Label>
      <Segmented
        value={s.effort ?? 'default'}
        onChange={(v) => update({ effort: v === 'default' ? null : v })}
        options={[{ label: 'auto', value: 'default' }, ...efforts.map((e) => ({ label: e, value: e }))]}
      />
      <Body muted style={{ fontSize: 12, marginTop: 6 }}>
        Higher effort means deeper reasoning, slower runs and more tokens. Medium suits most analyses. Haiku ignores
        this setting.
      </Body>
    </Card>
  );
}

function AutopilotCard({
  s,
  message,
  update,
}: {
  s: Settings;
  message?: string | null;
  update: (p: Record<string, unknown>, note?: string) => void;
}) {
  const ap = s.autopilot;
  const set = (p: Partial<Settings['autopilot']>) => update({ autopilot: p });
  return (
    <Card style={ap.enabled ? { borderColor: `${colors.accent}88` } : undefined}>
      <H2>Autopilot 🤖</H2>
      <Body muted style={{ fontSize: 13, marginBottom: space.sm }}>
        The trading-bot mode: once a day the agent team analyses every ticker below and trades the paper account on
        its own. Each ticker is a full analysis, so mind your budget.
      </Body>
      <Toggle label="Enabled" value={ap.enabled} onChange={(v) => set({ enabled: v })} />
      <TextSetting
        label="Tickers (comma separated)"
        value={ap.tickers.join(', ')}
        onSave={(v) => set({ tickers: v.split(',').map((x) => x.trim()).filter(Boolean) })}
      />
      <Row style={{ gap: space.sm }}>
        <View style={{ flex: 1 }}>
          <TextSetting label="Time (HH:MM)" value={ap.run_time} onSave={(v) => set({ run_time: v })} />
        </View>
        <View style={{ flex: 2 }}>
          <TextSetting
            label="Time zone"
            value={ap.timezone}
            onSave={(v) => set({ timezone: v })}
            hint="e.g. America/New_York, Europe/Istanbul"
          />
        </View>
      </Row>
      <Toggle label="Weekdays only" value={ap.weekdays_only} onChange={(v) => set({ weekdays_only: v })} />
      <Toggle
        label="Trade the decisions"
        hint="Off: autopilot only analyses and you execute from the Agents tab."
        value={ap.auto_execute}
        onChange={(v) => set({ auto_execute: v })}
      />
      <Body muted style={{ fontSize: 12 }}>
        Last run day: {ap.last_run_date ?? 'never'}
        {message ? `\n${message}` : ''}
      </Body>
      <Body muted style={{ fontSize: 12, marginTop: 4 }}>
        The server must be running at that time (keep your computer awake, or host it, see the README).
      </Body>
    </Card>
  );
}

function AccountCard() {
  const [cash, setCash] = useState('100000');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card>
      <H2>Paper account</H2>
      <Field
        label="Starting cash for a fresh account"
        value={cash}
        onChangeText={setCash}
        keyboardType="decimal-pad"
        style={{ marginTop: space.sm }}
      />
      <Button
        title="Reset account"
        kind="danger"
        loading={busy}
        onPress={() =>
          Alert.alert('Reset the paper account?', 'All positions, orders, trades and the equity curve are erased.', [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Reset',
              style: 'destructive',
              onPress: async () => {
                setBusy(true);
                try {
                  const a = await api.resetAccount(Number(cash));
                  setMsg(`Fresh account with ${money(a.cash)}`);
                } catch (e) {
                  setMsg((e as Error).message);
                } finally {
                  setBusy(false);
                }
              },
            },
          ])
        }
      />
      {msg ? <Body muted style={{ marginTop: space.sm }}>{msg}</Body> : null}
    </Card>
  );
}
