import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { RunRow } from '../../components/RunRow';
import {
  Body,
  Button,
  Card,
  Chips,
  Empty,
  ErrorBanner,
  Field,
  Label,
  Notice,
  Row,
  Screen,
  Segmented,
  Stepper,
  Toggle,
} from '../../components/ui';
import { api } from '../../lib/api';
import { todayIso, usd } from '../../lib/format';
import { colors, space } from '../../lib/theme';
import type { Preset, SettingsResponse, Usage } from '../../lib/types';
import { useApi } from '../../lib/useApi';

const ANALYSTS = [
  { label: 'Market (technicals)', value: 'market' },
  { label: 'Sentiment', value: 'social' },
  { label: 'News', value: 'news' },
  { label: 'Fundamentals', value: 'fundamentals' },
];

export default function Agents() {
  const params = useLocalSearchParams<{ ticker?: string }>();
  const runs = useApi(() => api.runs(), [], 5000);
  const meta = useApi(
    async () => {
      const [s, m, u] = await Promise.all([api.settings(), api.models(), api.usage()]);
      return { s, presets: m.presets, usage: u } as { s: SettingsResponse; presets: Preset[]; usage: Usage };
    },
    [],
  );

  const [ticker, setTicker] = useState('');
  const [dateMode, setDateMode] = useState<'today' | 'past'>('today');
  const [date, setDate] = useState(todayIso());
  const [analysts, setAnalysts] = useState<string[] | null>(null);
  const [debate, setDebate] = useState<number | null>(null);
  const [risk, setRisk] = useState<number | null>(null);
  const [preset, setPreset] = useState<string>('settings');
  const [autoExec, setAutoExec] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Opened from a ticker's screen: prefill it (adjusting state on a param change, during render).
  const [seenTicker, setSeenTicker] = useState<string | undefined>(undefined);
  if (params.ticker && params.ticker !== seenTicker) {
    setSeenTicker(params.ticker);
    setTicker(String(params.ticker));
  }

  const s = meta.data?.s.settings;
  const keySet = meta.data?.s.keys.anthropic.set;
  const chosenAnalysts = analysts ?? s?.analysts ?? ['market', 'social', 'news', 'fundamentals'];
  const debateRounds = debate ?? s?.max_debate_rounds ?? 1;
  const riskRounds = risk ?? s?.max_risk_rounds ?? 1;
  const auto = autoExec ?? s?.auto_execute ?? false;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = meta.data?.presets.find((x) => x.id === preset);
      const run = await api.startRun({
        ticker: ticker.trim(),
        trade_date: dateMode === 'today' ? undefined : date.trim(),
        analysts: chosenAnalysts,
        max_debate_rounds: debateRounds,
        max_risk_rounds: riskRounds,
        auto_execute: dateMode === 'today' ? auto : false,
        ...(p ? { quick_model: p.quick_model, deep_model: p.deep_model } : {}),
      });
      runs.refresh();
      router.push(`/run/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const avg = meta.data?.usage.avg_run_cost_usd;

  return (
    <Screen refreshing={runs.refreshing} onRefresh={runs.reload}>
      {meta.data && !keySet && (
        <Notice color={colors.warn}>
          Add your Anthropic API key in Settings to let the agents work. It is stored on your server, not on this
          phone.
        </Notice>
      )}
      <Card>
        <Label style={{ marginBottom: space.md }}>New analysis</Label>
        <Field
          label="Ticker"
          value={ticker}
          onChangeText={setTicker}
          autoCapitalize="characters"
          placeholder="NVDA"
        />
        <Label style={{ marginBottom: 6 }}>Analysis date</Label>
        <Segmented
          value={dateMode}
          onChange={setDateMode}
          options={[
            { label: 'Today (tradeable)', value: 'today' },
            { label: 'A past date', value: 'past' },
          ]}
        />
        {dateMode === 'past' && (
          <Field
            style={{ marginTop: space.md }}
            label="Date (YYYY-MM-DD)"
            value={date}
            onChangeText={setDate}
            hint="The agents only see data published by that day, so you can check their call against what happened next."
          />
        )}

        <Label style={{ marginTop: space.lg, marginBottom: 8 }}>Analyst team</Label>
        <Chips
          options={ANALYSTS}
          selected={chosenAnalysts}
          onToggle={(v) =>
            setAnalysts(
              chosenAnalysts.includes(v) ? chosenAnalysts.filter((a) => a !== v) : [...chosenAnalysts, v],
            )
          }
        />
        <View style={{ marginTop: space.md }}>
          <Stepper label="Bull vs bear debate rounds" value={debateRounds} onChange={setDebate} min={1} max={5} />
          <Stepper label="Risk team debate rounds" value={riskRounds} onChange={setRisk} min={1} max={5} />
        </View>

        <Label style={{ marginTop: space.md, marginBottom: 8 }}>Models</Label>
        <Chips
          options={[
            { label: `Settings (${s?.quick_model ?? '…'} / ${s?.deep_model ?? '…'})`, value: 'settings' },
            ...(meta.data?.presets ?? []).map((p) => ({ label: p.label, value: p.id })),
          ]}
          selected={[preset]}
          onToggle={setPreset}
        />
        {preset !== 'settings' && (
          <Body muted style={{ fontSize: 13, marginTop: 6 }}>
            {meta.data?.presets.find((p) => p.id === preset)?.description}
          </Body>
        )}

        {dateMode === 'today' && (
          <Toggle
            label="Trade the decision automatically"
            hint="Otherwise you review the proposal and tap Execute."
            value={auto}
            onChange={setAutoExec}
          />
        )}
        <ErrorBanner message={error} />
        <Button
          title="Start the agents"
          onPress={start}
          loading={busy}
          disabled={!ticker.trim() || chosenAnalysts.length === 0}
          style={{ marginTop: space.md }}
        />
        <Body muted style={{ fontSize: 12, marginTop: space.sm }}>
          A run makes dozens of Claude calls and takes a few minutes.
          {avg != null ? ` Your recent runs averaged ${usd(avg)}.` : ''} More debate rounds mean deeper and costlier
          runs.
        </Body>
      </Card>

      <Pressable onPress={() => router.push('/replays')}>
        <Card style={{ borderColor: `${colors.accent}55` }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>Strategy replay ⏪</Text>
              <Body muted style={{ fontSize: 13 }}>
                Let the agents trade a stretch of the past and compare them with buy-and-hold.
              </Body>
            </View>
            <Text style={{ color: colors.accent, fontSize: 22 }}>›</Text>
          </Row>
        </Card>
      </Pressable>

      <ErrorBanner message={runs.error} />
      <Card>
        <Label style={{ marginBottom: space.sm }}>Recent analyses</Label>
        {runs.data?.runs.length === 0 && <Empty title="No analyses yet">Start one above.</Empty>}
        {(runs.data?.runs ?? []).map((r) => (
          <RunRow key={r.id} run={r} />
        ))}
      </Card>
    </Screen>
  );
}
