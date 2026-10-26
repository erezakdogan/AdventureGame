import { router, Stack, useLocalSearchParams } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { LineChart } from '../../components/LineChart';
import {
  Body,
  Button,
  Card,
  ErrorBanner,
  KV,
  Label,
  Loading,
  Notice,
  RatingBadge,
  Row,
  Screen,
} from '../../components/ui';
import { api } from '../../lib/api';
import { money, pct, price, qty, usd } from '../../lib/format';
import { colors, pnlColor, space } from '../../lib/theme';
import { useApi } from '../../lib/useApi';

export default function ReplayScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const replayId = Number(id);
  const r = useApi(() => api.replay(replayId), [replayId], 4000);
  const rp = r.data;
  if (!rp) return r.error ? <Screen><ErrorBanner message={r.error} /></Screen> : <Loading />;

  const active = rp.status === 'queued' || rp.status === 'running';
  const s = rp.summary;
  const beat = s && s.buy_hold_return_pct != null ? s.return_pct - s.buy_hold_return_pct : null;

  return (
    <Screen refreshing={r.refreshing} onRefresh={r.reload}>
      <Stack.Screen options={{ title: `${rp.ticker} replay` }} />
      <Card>
        <Text style={{ color: colors.text, fontSize: 22, fontWeight: '800' }}>{rp.ticker}</Text>
        <Body muted style={{ fontSize: 13 }}>
          {rp.start_date} → {rp.end_date}, a decision every {rp.every_n_days} days, starting with {money(rp.starting_cash)}
        </Body>
        {active && (
          <>
            <Notice>
              Working on decision {rp.steps.length + 1}. Each one is a full agent analysis and takes a few minutes.
            </Notice>
            <Button
              title="Stop replay"
              kind="danger"
              small
              style={{ marginTop: space.sm, alignSelf: 'flex-start' }}
              onPress={() => api.cancelReplay(replayId).then(r.refresh)}
            />
          </>
        )}
        {rp.error ? <ErrorBanner message={rp.error} /> : null}
      </Card>

      {s && (
        <Card>
          <Row style={{ gap: space.lg }}>
            <View style={{ flex: 1 }}>
              <Label>Agents</Label>
              <Text style={{ color: pnlColor(s.return_pct), fontSize: 26, fontWeight: '800' }}>{pct(s.return_pct)}</Text>
              <Body muted style={{ fontSize: 12 }}>{money(s.final_equity)}</Body>
            </View>
            <View style={{ flex: 1 }}>
              <Label>Buy &amp; hold</Label>
              <Text style={{ color: pnlColor(s.buy_hold_return_pct), fontSize: 26, fontWeight: '800' }}>
                {pct(s.buy_hold_return_pct)}
              </Text>
              {beat != null ? (
                <Body style={{ fontSize: 12, color: pnlColor(beat) }}>
                  agents {beat >= 0 ? 'ahead' : 'behind'} by {Math.abs(beat).toFixed(2)} pts
                </Body>
              ) : null}
            </View>
          </Row>
          <View style={{ marginTop: space.lg }}>
            <LineChart
              series={[
                { values: s.curve.map((c) => c.equity), color: colors.accent, fill: true },
                { values: s.curve.map((c) => c.buy_hold), color: colors.muted, dashed: true },
              ]}
              baseline={rp.starting_cash}
              height={170}
            />
            <Row style={{ gap: space.lg, marginTop: 6 }}>
              <Text style={{ color: colors.accent, fontSize: 12 }}>━ agents</Text>
              <Text style={{ color: colors.muted, fontSize: 12 }}>┅ buy &amp; hold</Text>
            </Row>
          </View>
          <View style={{ marginTop: space.md }}>
            <KV k="Max drawdown" v={s.max_drawdown_pct != null ? `${s.max_drawdown_pct.toFixed(2)}%` : '—'} />
            <KV k="Decisions / trades" v={`${s.decisions} / ${s.trades}`} />
            <KV
              k="Ratings"
              v={Object.entries(s.ratings)
                .filter(([, n]) => n)
                .map(([k, n]) => `${k} ${n}`)
                .join(' · ') || '—'}
            />
            <KV k="Marked to market" v={`${s.marked_at} at ${price(s.final_price)}`} />
            <KV k="Claude cost" v={usd(s.cost_usd)} />
          </View>
          <Body muted style={{ fontSize: 11, marginTop: space.sm }}>
            A short replay is one sample, not proof of skill. Results swing with the model, the dates and the market.
          </Body>
        </Card>
      )}

      <Card>
        <Label style={{ marginBottom: space.sm }}>Decisions</Label>
        {rp.steps.length === 0 && <Body muted>No decisions yet.</Body>}
        {rp.steps.map((st, i) => (
          <Pressable
            key={`${st.date}-${i}`}
            disabled={!st.run_id}
            onPress={() => st.run_id && router.push(`/run/${st.run_id}`)}
            style={{ paddingVertical: space.md, borderTopWidth: 1, borderTopColor: colors.border }}
          >
            <Row style={{ justifyContent: 'space-between' }}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.text, fontWeight: '700' }}>{st.date}</Text>
                {st.status === 'completed' ? (
                  <Body muted style={{ fontSize: 12 }}>
                    {st.action === 'none'
                      ? 'no trade'
                      : `${st.action} ${qty(st.quantity)} at ${price(st.price)} on ${st.fill_date}`}{' '}
                    · equity {money(st.equity)}
                  </Body>
                ) : (
                  <Body muted style={{ fontSize: 12 }}>
                    {st.status}
                    {st.note ? `: ${st.note}` : ''}
                  </Body>
                )}
              </View>
              {st.rating ? <RatingBadge rating={st.rating} /> : null}
            </Row>
          </Pressable>
        ))}
      </Card>
    </Screen>
  );
}
