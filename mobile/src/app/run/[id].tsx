import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Text, View } from 'react-native';

import { Markdown } from '../../components/Markdown';
import { Pipeline } from '../../components/Pipeline';
import { statusColor } from '../../components/RunRow';
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
  Pill,
  RatingBadge,
  Row,
  Screen,
} from '../../components/ui';
import { api } from '../../lib/api';
import { duration, money, price, qty, todayIso, usd } from '../../lib/format';
import { colors, ratingColor, space } from '../../lib/theme';
import type { ChatMessage, Order, OrderPlan, Run, RunEvent } from '../../lib/types';

const SECTIONS: { key: string; label: string }[] = [
  { key: 'final_trade_decision', label: 'Final decision' },
  { key: 'trader_investment_plan', label: 'Trader' },
  { key: 'investment_plan', label: 'Research manager' },
  { key: 'bull_history', label: 'Bull' },
  { key: 'bear_history', label: 'Bear' },
  { key: 'market_report', label: 'Technicals' },
  { key: 'sentiment_report', label: 'Sentiment' },
  { key: 'news_report', label: 'News' },
  { key: 'fundamentals_report', label: 'Fundamentals' },
  { key: 'aggressive_history', label: 'Aggressive risk' },
  { key: 'conservative_history', label: 'Conservative risk' },
  { key: 'neutral_history', label: 'Neutral risk' },
];

const EVENT_ICON: Record<RunEvent['kind'], string> = {
  status: '•',
  tool: '🔧',
  agent: '🧠',
  decision: '🏁',
  trade: '💱',
  warning: '⚠️',
  error: '⛔',
};

export default function RunScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const runId = Number(id);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState('final_trade_decision');
  const lastEvent = useRef(0);

  const load = useCallback(async () => {
    try {
      const [r, ev] = await Promise.all([api.run(runId), api.runEvents(runId, lastEvent.current)]);
      setRun(r);
      if (ev.events.length) {
        lastEvent.current = ev.events[ev.events.length - 1].id;
        setEvents((prev) => [...prev, ...ev.events]);
      }
      setError(null);
      return r;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [runId]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const tick = async () => {
      const r = await load();
      if (stopped) return;
      const active = !r || r.status === 'queued' || r.status === 'running';
      timer = setTimeout(tick, active ? 2500 : 15000);
    };
    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [load]);

  if (!run) return error ? <Screen><ErrorBanner message={error} /></Screen> : <Loading />;

  const active = run.status === 'queued' || run.status === 'running';
  const reports = run.reports ?? {};
  const available = SECTIONS.filter((s) => reports[s.key]);
  const shown = reports[section] ? section : available[0]?.key;

  return (
    <Screen>
      <Stack.Screen options={{ title: `${run.ticker} analysis` }} />
      <ErrorBanner message={error} />

      <Card>
        <Row style={{ justifyContent: 'space-between' }}>
          <View>
            <Text style={{ color: colors.text, fontSize: 24, fontWeight: '800' }}>{run.ticker}</Text>
            <Body muted style={{ fontSize: 13 }}>
              as of {run.trade_date} · {duration(run.started_at, run.finished_at)}
            </Body>
          </View>
          <View style={{ alignItems: 'flex-end', gap: 6 }}>
            <Pill text={run.status} color={statusColor[run.status]} />
            {run.usage?.cost_usd != null && run.usage.cost_usd > 0 && (
              <Body muted style={{ fontSize: 12 }}>
                ≈{usd(run.usage.cost_usd)} · {run.usage.calls ?? 0} Claude calls
              </Body>
            )}
          </View>
        </Row>
        <Body muted style={{ fontSize: 12, marginTop: space.sm }}>
          {run.options.quick_model} (analysts) · {run.options.deep_model} (managers) · effort{' '}
          {run.options.effort ?? 'default'} · {run.options.max_debate_rounds}/{run.options.max_risk_rounds} debate
          rounds
        </Body>
        {active && (
          <Button
            title="Cancel run"
            kind="danger"
            small
            style={{ marginTop: space.md, alignSelf: 'flex-start' }}
            onPress={() => api.cancelRun(runId).then(load).catch((e) => setError(e.message))}
          />
        )}
      </Card>

      {run.status === 'failed' && <ErrorBanner message={run.error} />}
      {run.status === 'completed' && <Decision run={run} onChange={load} />}

      <Card>
        <Label style={{ marginBottom: space.md }}>The trading firm</Label>
        <Pipeline agents={run.agents} teams={run.teams} />
      </Card>

      {available.length > 0 && (
        <Card>
          <Label style={{ marginBottom: space.md }}>Reports</Label>
          <Chips
            options={available.map((s) => ({ label: s.label, value: s.key }))}
            selected={shown ? [shown] : []}
            onToggle={setSection}
          />
          <Divider />
          {shown ? <Markdown>{reports[shown]}</Markdown> : null}
        </Card>
      )}

      {run.status === 'completed' && <AskClaude runId={runId} />}

      <Card>
        <Label style={{ marginBottom: space.sm }}>Activity log</Label>
        {events.length === 0 ? <Body muted>Waiting for the first step…</Body> : null}
        {[...events]
          .reverse()
          .slice(0, active ? 60 : 200)
          .map((e) => (
            <Row key={e.id} style={{ alignItems: 'flex-start', gap: 8, paddingVertical: 4 }}>
              <Text style={{ width: 22 }}>{EVENT_ICON[e.kind] ?? '•'}</Text>
              <View style={{ flex: 1 }}>
                {e.agent && e.kind !== 'agent' ? (
                  <Text style={{ color: colors.accent, fontSize: 12, fontWeight: '700' }}>{e.agent}</Text>
                ) : null}
                <Text
                  style={{
                    color: e.kind === 'error' ? colors.down : e.kind === 'warning' ? colors.warn : colors.text,
                    fontSize: 13,
                    fontFamily: e.kind === 'tool' ? 'Courier' : undefined,
                  }}
                >
                  {e.text}
                </Text>
              </View>
            </Row>
          ))}
      </Card>

      {!active && (
        <Button
          title="Delete this analysis"
          kind="ghost"
          onPress={() =>
            Alert.alert('Delete analysis?', 'Its reports and chat are removed. Trades it made stay.', [
              { text: 'Cancel', style: 'cancel' },
              {
                text: 'Delete',
                style: 'destructive',
                onPress: () =>
                  api
                    .deleteRun(runId)
                    .then(() => router.back())
                    .catch((e) => setError(e.message)),
              },
            ])
          }
        />
      )}
    </Screen>
  );
}

function Decision({ run, onChange }: { run: Run; onChange: () => void }) {
  const p = run.proposal;
  const [plan, setPlan] = useState<OrderPlan | null>(p?.plan ?? null);
  const [customQty, setCustomQty] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placed, setPlaced] = useState<Order[] | null>(null);
  const executed = run.executed_order_ids.length > 0 || !!placed;
  const rating = run.rating ?? 'REVIEW';

  const refresh = async () => {
    setError(null);
    try {
      setPlan(await api.refreshPlan(run.id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const execute = async () => {
    setBusy(true);
    setError(null);
    try {
      const q = customQty.trim() ? Number(customQty) : undefined;
      if (q !== undefined && !(q > 0)) throw new Error('Quantity must be a positive number');
      const res = await api.executeRun(run.id, q);
      setPlaced(res.orders);
      if (res.run.proposal?.plan) setPlan(res.run.proposal.plan);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card style={{ borderColor: `${ratingColor[rating]}66` }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <Label>Portfolio manager&apos;s call</Label>
        <RatingBadge rating={rating} large />
      </Row>
      {p?.decision.executive_summary ? (
        <Body style={{ marginTop: space.md }}>{p.decision.executive_summary}</Body>
      ) : null}
      <View style={{ marginTop: space.sm }}>
        {p?.decision.price_target ? <KV k="Price target" v={price(p.decision.price_target)} /> : null}
        {p?.decision.time_horizon ? <KV k="Time horizon" v={p.decision.time_horizon} /> : null}
        {p?.trader.action ? <KV k="Trader's action" v={p.trader.action} /> : null}
        {p?.trader.entry_price ? <KV k="Entry" v={price(p.trader.entry_price)} /> : null}
        {p?.trader.stop_loss ? <KV k="Stop-loss" v={price(p.trader.stop_loss)} /> : null}
        {p?.trader.position_sizing ? <KV k="Trader's sizing" v={p.trader.position_sizing} /> : null}
      </View>
      {p?.memory_note ? <Body muted style={{ fontSize: 12 }}>{p.memory_note}</Body> : null}

      {run.source !== 'replay' && (
        <>
          <Divider />
          <H2 style={{ marginBottom: 6 }}>Paper order</H2>
          {plan ? (
            <>
              {plan.action === 'none' ? (
                <Body muted>{plan.reason}</Body>
              ) : (
                <>
                  <Text
                    style={{
                      color: plan.action === 'buy' ? colors.up : colors.down,
                      fontSize: 20,
                      fontWeight: '800',
                    }}
                  >
                    {plan.action.toUpperCase()} {qty(plan.quantity)} {run.ticker}
                  </Text>
                  <Body muted style={{ fontSize: 13 }}>
                    ≈{money(plan.estimated_value)} at {price(plan.reference_price)} · {plan.reason}
                  </Body>
                  {plan.stop_loss ? <KV k="Protective stop" v={price(plan.stop_loss)} /> : null}
                  {plan.take_profit ? <KV k="Take-profit" v={price(plan.take_profit)} /> : null}
                </>
              )}
              {plan.notes.map((n) => (
                <Body key={n} muted style={{ fontSize: 12 }}>
                  · {n}
                </Body>
              ))}
            </>
          ) : (
            <Body muted>No plan yet.</Body>
          )}

          {executed ? (
            <Notice color={colors.up}>
              Executed.{' '}
              {placed
                ? placed.map((o) => `${o.side} ${qty(o.quantity)} ${o.order_type} → ${o.status}`).join('; ')
                : 'See the Activity tab for the orders.'}
            </Notice>
          ) : run.trade_date !== todayIso() && plan?.action !== 'none' ? (
            <Notice color={colors.warn}>
              This analysis is dated {run.trade_date}. Executing trades it at today&apos;s price.
            </Notice>
          ) : null}

          <ErrorBanner message={error} />
          {!executed && plan && plan.action !== 'none' && (
            <>
              <Field
                style={{ marginTop: space.md }}
                label="Quantity (optional override)"
                value={customQty}
                onChangeText={setCustomQty}
                keyboardType="decimal-pad"
                placeholder={qty(plan.quantity)}
              />
              <Button
                title={`Execute ${plan.action}`}
                kind={plan.action === 'buy' ? 'buy' : 'sell'}
                onPress={execute}
                loading={busy}
              />
            </>
          )}
          {!executed && (
            <Button title="Re-size against my account now" kind="ghost" small onPress={refresh} />
          )}
        </>
      )}
    </Card>
  );
}

function AskClaude({ runId }: { runId: number }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .chat(runId)
      .then((r) => setMessages(r.messages))
      .catch(() => undefined);
  }, [runId]);

  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { id: -Date.now(), role: 'user', content: question }]);
    setQ('');
    try {
      const a = await api.ask(runId, question);
      setMessages((m) => [...m, a]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const starters = [
    'Explain this decision like I am new to trading',
    'Where did the bull and bear disagree most?',
    'What would make the agents change their mind?',
  ];

  return (
    <Card>
      <Label style={{ marginBottom: space.sm }}>Ask Claude about this analysis</Label>
      {messages.length === 0 && (
        <View style={{ gap: 6, marginBottom: space.sm }}>
          {starters.map((s) => (
            <Button key={s} title={s} kind="secondary" small onPress={() => ask(s)} disabled={busy} />
          ))}
        </View>
      )}
      {messages.map((m) => (
        <View
          key={m.id}
          style={{
            alignSelf: m.role === 'user' ? 'flex-end' : 'stretch',
            backgroundColor: m.role === 'user' ? `${colors.accent}26` : colors.surfaceAlt,
            borderRadius: 12,
            padding: space.md,
            marginBottom: space.sm,
            maxWidth: m.role === 'user' ? '85%' : '100%',
          }}
        >
          {m.role === 'user' ? <Body>{m.content}</Body> : <Markdown>{m.content}</Markdown>}
        </View>
      ))}
      {busy && <Body muted>Claude is reading the reports…</Body>}
      <ErrorBanner message={error} />
      <Field value={q} onChangeText={setQ} placeholder="Ask a follow-up question" multiline />
      <Button title="Ask" onPress={() => ask(q)} loading={busy} disabled={!q.trim()} small />
    </Card>
  );
}
