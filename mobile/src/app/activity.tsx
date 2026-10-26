import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { Body, Button, Card, Empty, ErrorBanner, Pill, Row, Screen, Segmented } from '../components/ui';
import { api } from '../lib/api';
import { price, qty, signedMoney, when } from '../lib/format';
import { colors, pnlColor, space } from '../lib/theme';
import type { Order, Trade } from '../lib/types';
import { useApi } from '../lib/useApi';

type Tab = 'open' | 'orders' | 'trades';

const SOURCE_LABEL: Record<string, string> = {
  manual: 'you',
  agent: 'agents',
  autopilot: 'autopilot',
  'agent-stop': 'agent stop',
  'agent-target': 'agent target',
};

const ORDER_COLOR: Record<Order['status'], string> = {
  open: colors.accent,
  filled: colors.up,
  cancelled: colors.muted,
  rejected: colors.down,
};

export default function Activity() {
  const [tab, setTab] = useState<Tab>('open');
  const data = useApi(
    async () => {
      if (tab === 'trades') return { trades: (await api.trades()).trades, orders: [] as Order[] };
      return { orders: (await api.orders(tab === 'open' ? 'open' : undefined)).orders, trades: [] as Trade[] };
    },
    [tab],
    20000,
  );
  const [error, setError] = useState<string | null>(null);

  return (
    <Screen refreshing={data.refreshing} onRefresh={data.reload}>
      <Segmented
        value={tab}
        onChange={setTab}
        options={[
          { label: 'Open orders', value: 'open' },
          { label: 'All orders', value: 'orders' },
          { label: 'Trades', value: 'trades' },
        ]}
      />
      <ErrorBanner message={data.error ?? error} />
      {tab === 'open' && (
        <Body muted style={{ fontSize: 12 }}>
          Limit and stop orders, including the agents&apos; protective stops, are checked against live prices about
          once a minute while the server runs.
        </Body>
      )}
      <Card>
        {tab !== 'trades' &&
          (data.data?.orders.length ? (
            data.data.orders.map((o) => (
              <View key={o.id} style={{ paddingVertical: space.md, borderTopWidth: 1, borderTopColor: colors.border }}>
                <Row style={{ justifyContent: 'space-between' }}>
                  <Pressable onPress={() => router.push(`/symbol/${encodeURIComponent(o.symbol)}`)} style={{ flex: 1 }}>
                    <Text style={{ color: o.side === 'buy' ? colors.up : colors.down, fontWeight: '800' }}>
                      {o.side.toUpperCase()} {qty(o.quantity)} {o.symbol}
                    </Text>
                    <Body muted style={{ fontSize: 12 }}>
                      {o.order_type}
                      {o.limit_price ? ` @ ${price(o.limit_price)}` : ''}
                      {o.stop_price ? ` stop ${price(o.stop_price)}` : ''} · by {SOURCE_LABEL[o.source] ?? o.source} ·{' '}
                      {when(o.created_at)}
                    </Body>
                    {o.fill_price ? (
                      <Body style={{ fontSize: 13 }}>
                        Filled at {price(o.fill_price)}
                        {o.commission ? ` · fee ${price(o.commission)}` : ''}
                      </Body>
                    ) : null}
                    {o.reject_reason ? (
                      <Body muted style={{ fontSize: 12 }}>
                        {o.reject_reason}
                      </Body>
                    ) : null}
                    {o.note ? (
                      <Body muted style={{ fontSize: 12 }} numberOfLines={2}>
                        {o.note}
                      </Body>
                    ) : null}
                  </Pressable>
                  <View style={{ alignItems: 'flex-end', gap: 6 }}>
                    <Pill text={o.status} color={ORDER_COLOR[o.status]} />
                    {o.status === 'open' && (
                      <Button
                        title="Cancel"
                        small
                        kind="danger"
                        onPress={() =>
                          api
                            .cancelOrder(o.id)
                            .then(() => data.refresh())
                            .catch((e) => setError(e.message))
                        }
                      />
                    )}
                    {o.run_id ? (
                      <Button title="Analysis" small kind="ghost" onPress={() => router.push(`/run/${o.run_id}`)} />
                    ) : null}
                  </View>
                </Row>
              </View>
            ))
          ) : (
            <Empty title={tab === 'open' ? 'No waiting orders' : 'No orders yet'} />
          ))}

        {tab === 'trades' &&
          (data.data?.trades.length ? (
            data.data.trades.map((t) => (
              <Row
                key={t.id}
                style={{
                  justifyContent: 'space-between',
                  paddingVertical: space.md,
                  borderTopWidth: 1,
                  borderTopColor: colors.border,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ color: t.side === 'buy' ? colors.up : colors.down, fontWeight: '800' }}>
                    {t.side.toUpperCase()} {qty(t.quantity)} {t.symbol}
                  </Text>
                  <Body muted style={{ fontSize: 12 }}>
                    at {price(t.price)} · by {SOURCE_LABEL[t.source] ?? t.source} · {when(t.ts)}
                  </Body>
                </View>
                {t.realized_pnl != null ? (
                  <Text style={{ color: pnlColor(t.realized_pnl), fontWeight: '700' }}>{signedMoney(t.realized_pnl)}</Text>
                ) : null}
              </Row>
            ))
          ) : (
            <Empty title="No trades yet" />
          ))}
      </Card>
    </Screen>
  );
}
