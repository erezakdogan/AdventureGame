import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import { AccuracyCard } from '../../components/Forecasts';
import { LineChart } from '../../components/LineChart';
import {
  Body,
  Button,
  Card,
  ErrorBanner,
  Field,
  KV,
  Label,
  Loading,
  Notice,
  Pill,
  Row,
  Screen,
  Stepper,
  Toggle,
} from '../../components/ui';
import { api } from '../../lib/api';
import { money, pct, price, qty, signedMoney, usd, when, whenFuture } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import type { Fund, FundConfig, FundCycle } from '../../lib/types';
import { useApi } from '../../lib/useApi';

export default function FundScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const fundId = Number(id);
  const [error, setError] = useState<string | null>(null);
  const fund = useApi(() => api.fund(fundId), [fundId], 8000);
  const equity = useApi(() => api.fundEquity(fundId), [fundId], 30000);
  const cycles = useApi(() => api.fundCycles(fundId), [fundId], 8000);

  const f = fund.data;
  if (!f) return fund.error ? <Screen><ErrorBanner message={fund.error} /></Screen> : <Loading />;

  const points = equity.data?.points ?? [];
  const values = points.map((p) => p.equity);
  const firstBench = points.find((p) => p.benchmark)?.benchmark ?? f.benchmark_start;
  const benchValues =
    firstBench && values.length
      ? points.map((p) => (p.benchmark ? (values[0] * p.benchmark) / firstBench : NaN)).filter((v) => Number.isFinite(v))
      : [];
  const beat = f.benchmark_return_pct != null ? f.total_pnl_pct - f.benchmark_return_pct : null;
  const lastCycle = cycles.data?.cycles[0];
  const running = f.running || lastCycle?.status === 'running';

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      fund.refresh();
      cycles.refresh();
      equity.refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Screen
      refreshing={fund.refreshing}
      onRefresh={() => {
        fund.reload();
        cycles.reload();
        equity.reload();
      }}
    >
      <Stack.Screen options={{ title: f.name }} />
      <ErrorBanner message={error} />
      <Card>
        <Row style={{ gap: 6 }}>
          <Pill text={f.style_label} color={colors.info} />
          <Pill text={running ? 'trading now' : f.status} color={running ? colors.accent : f.status === 'active' ? colors.up : colors.warn} />
        </Row>
        <Text style={{ color: colors.text, fontSize: 32, fontWeight: '800', marginTop: space.sm }}>{money(f.equity)}</Text>
        <Text style={{ color: pnlColor(f.total_pnl), fontWeight: '700' }}>
          {signedMoney(f.total_pnl)} ({pct(f.total_pnl_pct)}) since start
        </Text>
        <Body style={{ color: pnlColor(beat), fontSize: 13 }}>
          {f.benchmark_symbol}: {pct(f.benchmark_return_pct)}
          {beat != null ? ` · fund ${beat >= 0 ? 'ahead' : 'behind'} by ${Math.abs(beat).toFixed(2)} pts` : ''}
        </Body>
        <View style={{ marginTop: space.md }}>
          <LineChart
            series={[
              { values, color: colors.accent, fill: true },
              { values: benchValues, color: colors.muted, dashed: true },
            ]}
            baseline={values[0]}
            height={150}
          />
          <Row style={{ gap: space.lg, marginTop: 6 }}>
            <Text style={{ color: colors.accent, fontSize: 12 }}>━ fund</Text>
            <Text style={{ color: colors.muted, fontSize: 12 }}>┅ {f.benchmark_symbol} (same start)</Text>
          </Row>
        </View>
        {running ? (
          <Notice>Claude is reviewing the market and the fund right now…</Notice>
        ) : (
          <Body muted style={{ fontSize: 12, marginTop: space.sm }}>
            {f.status === 'paused'
              ? 'Paused: no automatic trading.'
              : `Next check ${f.next_cycle_at ? whenFuture(f.next_cycle_at) : 'soon'}`}
            {f.last_cycle_at ? ` · last ${when(f.last_cycle_at)}` : ''}
          </Body>
        )}
        {f.last_error ? <ErrorBanner message={`Last check failed: ${f.last_error}`} /> : null}
        <Row style={{ gap: space.sm, marginTop: space.md }}>
          <Button
            title="Run a check now"
            style={{ flex: 1 }}
            disabled={running}
            onPress={() => act(() => api.runFundCycle(fundId))}
          />
          <Button
            title={f.status === 'active' ? 'Pause' : 'Resume'}
            kind="secondary"
            onPress={() => act(() => api.updateFund(fundId, { status: f.status === 'active' ? 'paused' : 'active' }))}
          />
        </Row>
      </Card>

      <Card>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          <Stat label="Cash" value={money(f.cash)} />
          <Stat label="Invested" value={money(f.equity - f.cash)} />
          <Stat label="Realized P&L" value={signedMoney(f.realized_pnl)} color={pnlColor(f.realized_pnl)} />
          <Stat label="Win rate" value={f.win_rate_pct != null ? `${f.win_rate_pct.toFixed(0)}% of ${f.closed_trades}` : '—'} />
          <Stat label="Max drawdown" value={`${f.max_drawdown_pct.toFixed(2)}%`} />
          <Stat label="Trades" value={`${f.trade_count}`} />
          <Stat label="Checks run" value={`${f.cycles}`} />
          <Stat label="Claude cost" value={usd(f.claude_cost_usd)} />
        </View>
      </Card>

      <AccuracyCard
        stats={f.accuracy}
        title="How accurate its forecasts are"
        link={{ label: 'See every forecast', href: `/track-record?fund_id=${fundId}&title=${encodeURIComponent(f.name)}` }}
      />

      <Card>
        <Label style={{ marginBottom: space.sm }}>Holdings</Label>
        {(f.positions ?? []).length === 0 ? (
          <Body muted>All cash right now.</Body>
        ) : (
          (f.positions ?? []).map((p) => (
            <Row
              key={p.symbol}
              style={{ justifyContent: 'space-between', paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border }}
            >
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.text, fontWeight: '700' }}>{p.symbol}</Text>
                <Body muted style={{ fontSize: 12 }}>
                  {qty(p.quantity)} @ {price(p.avg_price)} · {p.weight_pct.toFixed(1)}%
                </Body>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <Text style={{ color: colors.text, fontWeight: '700' }}>{money(p.market_value)}</Text>
                <Text style={{ color: pnlColor(p.unrealized_pnl), fontSize: 12 }}>
                  {signedMoney(p.unrealized_pnl)} ({pct(p.unrealized_pnl_pct)})
                </Text>
              </View>
            </Row>
          ))
        )}
      </Card>

      <Card>
        <Label style={{ marginBottom: space.sm }}>Trading checks</Label>
        {(cycles.data?.cycles ?? []).length === 0 && <Body muted>No checks yet.</Body>}
        {(cycles.data?.cycles ?? []).map((c) => (
          <CycleRow key={c.id} c={c} />
        ))}
      </Card>

      <FundSettings f={f} onSaved={() => fund.refresh()} onError={setError} />

      <DepositCard fundId={fundId} onDone={() => fund.refresh()} />

      <Button
        title="Delete this fund"
        kind="ghost"
        onPress={() =>
          Alert.alert('Delete this fund?', 'Its wallet, trades, checks and forecasts are erased.', [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Delete',
              style: 'destructive',
              onPress: () =>
                api
                  .deleteFund(fundId)
                  .then(() => router.back())
                  .catch((e) => setError(e.message)),
            },
          ])
        }
      />
    </Screen>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={{ width: '50%', paddingVertical: 6 }}>
      <Text style={{ color: colors.muted, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: color ?? colors.text, fontSize: 16, fontWeight: '700' }}>{value}</Text>
    </View>
  );
}

const CYCLE_COLOR: Record<FundCycle['status'], string> = {
  running: colors.accent,
  completed: colors.up,
  failed: colors.down,
  skipped: colors.muted,
};

function CycleRow({ c }: { c: FundCycle }) {
  const trades = c.decisions.filter((d) => d.executed === 'filled');
  const buys = trades.filter((d) => d.side === 'buy').length;
  const sells = trades.length - buys;
  const change = c.equity_after != null && c.equity_before != null ? c.equity_after - c.equity_before : null;
  return (
    <Pressable
      onPress={() => router.push(`/funds/cycle/${c.id}`)}
      style={({ pressed }) => ({ paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border, opacity: pressed ? 0.7 : 1 })}
    >
      <Row style={{ justifyContent: 'space-between' }}>
        <View style={{ flex: 1 }}>
          <Row style={{ gap: 6 }}>
            <Text style={{ color: colors.text, fontWeight: '700' }}>{when(c.started_at)}</Text>
            <Pill text={c.status} color={CYCLE_COLOR[c.status]} />
          </Row>
          <Body muted numberOfLines={2} style={{ fontSize: 12, marginTop: 2 }}>
            {c.error ?? c.market_view ?? 'Working…'}
          </Body>
        </View>
        <View style={{ alignItems: 'flex-end', marginLeft: space.sm }}>
          <Text style={{ color: colors.text, fontSize: 13 }}>
            {buys ? `${buys} buy${buys > 1 ? 's' : ''}` : ''}
            {buys && sells ? ' · ' : ''}
            {sells ? `${sells} sell${sells > 1 ? 's' : ''}` : ''}
            {!buys && !sells && c.status === 'completed' ? 'no trades' : ''}
          </Text>
          {change != null && Math.abs(change) > 0.005 ? (
            <Text style={{ color: pnlColor(change), fontSize: 12 }}>{signedMoney(change)}</Text>
          ) : null}
        </View>
      </Row>
    </Pressable>
  );
}

function FundSettings({ f, onSaved, onError }: { f: Fund; onSaved: () => void; onError: (m: string | null) => void }) {
  const c = f.config;
  const [instructions, setInstructions] = useState(c.instructions);
  const save = async (patch: Partial<FundConfig>) => {
    onError(null);
    try {
      await api.updateFund(f.id, patch);
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    }
  };
  return (
    <Card>
      <Label style={{ marginBottom: space.sm }}>Fund settings</Label>
      <KV k="Frequency" v={f.style === 'custom' ? `every ${c.interval_minutes} min` : f.style_label} />
      <KV k="Brain" v={`${c.model}${c.deep_dive ? ` + agent team on ${c.deep_dive} pick(s)` : ''}`} />
      <KV k="Universe" v={`${c.universe.length} tickers`} />
      <Body muted style={{ fontSize: 12 }}>{c.universe.join(', ')}</Body>
      <Stepper label="Max positions" value={c.max_positions} min={1} max={20} onChange={(v) => save({ max_positions: v })} />
      <Stepper
        label="Max per position"
        value={c.max_position_pct}
        min={5}
        max={100}
        step={5}
        format={(v) => `${v}%`}
        onChange={(v) => save({ max_position_pct: v })}
      />
      <Stepper
        label="Cash reserve"
        value={c.cash_reserve_pct}
        min={0}
        max={50}
        step={5}
        format={(v) => `${v}%`}
        onChange={(v) => save({ cash_reserve_pct: v })}
      />
      <Toggle label="Stop-loss on buys" value={c.use_stop_loss} onChange={(v) => save({ use_stop_loss: v })} />
      <Toggle label="Take profit at forecast" value={c.use_take_profit} onChange={(v) => save({ use_take_profit: v })} />
      {(f.style === 'hourly' || f.style === 'day' || f.style === 'custom') && (
        <Toggle
          label="Close everything before the US close"
          value={c.flatten_at_close}
          onChange={(v) => save({ flatten_at_close: v })}
        />
      )}
      <Field
        style={{ marginTop: space.sm }}
        label="Your instructions to Claude"
        value={instructions}
        onChangeText={setInstructions}
        multiline
        onEndEditing={() => instructions !== c.instructions && save({ instructions })}
      />
    </Card>
  );
}

function DepositCard({ fundId, onDone }: { fundId: number; onDone: () => void }) {
  const [amount, setAmount] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card>
      <Label style={{ marginBottom: space.sm }}>Add paper money</Label>
      <Row style={{ gap: space.sm }}>
        <Field
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
          placeholder="1000"
          style={{ flex: 1, marginBottom: 0 }}
        />
        <Button
          title="Add"
          kind="secondary"
          onPress={async () => {
            setMsg(null);
            try {
              const f = await api.depositFund(fundId, Number(amount));
              setMsg(`Added. Cash is now ${money(f.cash)}.`);
              setAmount('');
              onDone();
            } catch (e) {
              setMsg((e as Error).message);
            }
          }}
        />
      </Row>
      <Body muted style={{ fontSize: 12, marginTop: 6 }}>
        {msg ?? 'Deposits raise the starting basis too, so they do not count as profit.'}
      </Body>
    </Card>
  );
}
