import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Body, Button, Card, Empty, ErrorBanner, Field, Label, Pill, Row, Screen, Stepper } from '../../components/ui';
import { api } from '../../lib/api';
import { daysAgoIso, pct, usd, when } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import { useApi } from '../../lib/useApi';

const STATUS_COLOR: Record<string, string> = {
  queued: colors.muted,
  running: colors.accent,
  completed: colors.up,
  failed: colors.down,
  cancelled: colors.warn,
};

function gridSize(start: string, end: string, every: number) {
  const a = Date.parse(start);
  const b = Math.min(Date.parse(end), Date.now() - 86400000);
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return 0;
  return Math.floor((b - a) / 86400000 / every) + 1;
}

export default function Replays() {
  const list = useApi(() => api.replays(), [], 5000);
  const usage = useApi(() => api.usage(), []);
  const [ticker, setTicker] = useState('');
  const [start, setStart] = useState(daysAgoIso(63));
  const [end, setEnd] = useState(daysAgoIso(7));
  const [every, setEvery] = useState(7);
  const [cash, setCash] = useState('10000');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const n = gridSize(start, end, every);
  const max = list.data?.max_steps ?? 20;
  const avg = usage.data?.avg_run_cost_usd;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.startReplay({
        ticker: ticker.trim(),
        start_date: start.trim(),
        end_date: end.trim(),
        every_n_days: every,
        starting_cash: Number(cash),
      });
      router.push(`/replays/${r.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen refreshing={list.refreshing} onRefresh={list.reload}>
      <Card>
        <Label style={{ marginBottom: space.sm }}>New replay</Label>
        <Body muted style={{ fontSize: 13, marginBottom: space.md }}>
          On each date the full agent team analyses the ticker using only data published by then. Its call is
          traded at the next close in a separate simulated account, so you can see how the bot would have done
          against simply buying and holding.
        </Body>
        <Field label="Ticker" value={ticker} onChangeText={setTicker} autoCapitalize="characters" placeholder="NVDA" />
        <Row style={{ gap: space.sm }}>
          <Field label="From" value={start} onChangeText={setStart} style={{ flex: 1 }} />
          <Field label="To" value={end} onChangeText={setEnd} style={{ flex: 1 }} />
        </Row>
        <Stepper label="Decide every" value={every} min={1} max={30} onChange={setEvery} format={(v) => `${v}d`} />
        <Field label="Starting cash" value={cash} onChangeText={setCash} keyboardType="decimal-pad" />
        <Body style={{ fontSize: 13, color: n > max ? colors.down : colors.muted }}>
          {n} decision date{n === 1 ? '' : 's'}
          {n > max ? ` (max ${max})` : ''}
          {avg != null && n > 0 ? ` · roughly ${usd(avg * n)} at your average run cost` : ''}
        </Body>
        <ErrorBanner message={error} />
        <Button
          title="Start replay"
          onPress={submit}
          loading={busy}
          disabled={!ticker.trim() || n < 1 || n > max}
          style={{ marginTop: space.md }}
        />
      </Card>

      <ErrorBanner message={list.error} />
      <Card>
        <Label style={{ marginBottom: space.sm }}>Past replays</Label>
        {list.data?.replays.length === 0 && <Empty title="No replays yet" />}
        {(list.data?.replays ?? []).map((r) => {
          const done = r.steps.filter((s) => s.status === 'completed').length;
          const total = gridSize(r.start_date, r.end_date, r.every_n_days);
          return (
            <Pressable
              key={r.id}
              onPress={() => router.push(`/replays/${r.id}`)}
              style={{ paddingVertical: space.md, borderTopWidth: 1, borderTopColor: colors.border }}
            >
              <Row style={{ justifyContent: 'space-between' }}>
                <View style={{ flex: 1 }}>
                  <Row style={{ gap: space.sm }}>
                    <Text style={{ color: colors.text, fontWeight: '700', fontSize: 16 }}>{r.ticker}</Text>
                    <Pill text={r.status} color={STATUS_COLOR[r.status]} />
                  </Row>
                  <Body muted style={{ fontSize: 12 }}>
                    {r.start_date} → {r.end_date} · every {r.every_n_days}d · {when(r.created_at)}
                  </Body>
                </View>
                {r.summary ? (
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={{ color: pnlColor(r.summary.return_pct), fontWeight: '800' }}>
                      {pct(r.summary.return_pct)}
                    </Text>
                    <Body muted style={{ fontSize: 12 }}>
                      hold {pct(r.summary.buy_hold_return_pct)}
                    </Body>
                  </View>
                ) : (
                  <Text style={{ color: colors.accent }}>
                    {done}/{total}
                  </Text>
                )}
              </Row>
            </Pressable>
          );
        })}
      </Card>
    </Screen>
  );
}
