import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import {
  Body,
  Button,
  Card,
  Chips,
  ErrorBanner,
  Field,
  Label,
  Loading,
  Screen,
  Segmented,
  Stepper,
  Toggle,
} from '../../components/ui';
import { api } from '../../lib/api';
import { money } from '../../lib/format';
import { colors, space } from '../../lib/theme';
import type { FundStyle } from '../../lib/types';
import { useApi } from '../../lib/useApi';

const UNIVERSE_LABELS: Record<string, string> = {
  us_megacaps: 'US mega caps',
  us_etfs: 'US ETFs',
  crypto: 'Crypto',
  global: 'Global',
  ai_semis: 'AI & chips',
};

const STYLE_HINT: Record<FundStyle, string> = {
  hourly: 'Checks the market every hour while it is open and aims for moves that play out within hours. Flat by the close.',
  day: 'Trades a few times a day, expects each move within the session, and closes everything before the bell.',
  swing: 'Reviews the book once a day (10:00 New York) and holds for days to a few weeks.',
  position: 'Reviews weekly and holds for one to six months. Cheapest to run.',
  custom: 'Pick your own interval between checks.',
};

const CYCLES_PER_DAY: Record<FundStyle, number> = { hourly: 7, day: 4, swing: 1, position: 0.2, custom: 0 };

export default function NewFund() {
  const meta = useApi(async () => {
    const [catalog, usage] = await Promise.all([api.fundCatalog(), api.usage()]);
    return { catalog, usage };
  });
  const [name, setName] = useState('My AI fund');
  const [cash, setCash] = useState('10000');
  const [style, setStyle] = useState<FundStyle>('swing');
  const [intervalMin, setIntervalMin] = useState(240);
  const [universes, setUniverses] = useState<string[]>(['us_megacaps']);
  const [extra, setExtra] = useState('');
  const [maxPositions, setMaxPositions] = useState(5);
  const [maxPct, setMaxPct] = useState(25);
  const [reserve, setReserve] = useState(5);
  const [model, setModel] = useState('claude-opus-5-5');
  const [deepDive, setDeepDive] = useState(0);
  const [stopLoss, setStopLoss] = useState(true);
  const [takeProfit, setTakeProfit] = useState(true);
  const [news, setNews] = useState(true);
  const [marketHours, setMarketHours] = useState(true);
  const [instructions, setInstructions] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!meta.data) return meta.error ? <Screen><ErrorBanner message={meta.error} /></Screen> : <Loading />;
  const { catalog } = meta.data;

  const tickers = Array.from(
    new Set([
      ...universes.flatMap((u) => catalog.universes[u] ?? []),
      ...extra
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ]),
  );
  const perDay = style === 'custom' ? (6.5 * 60) / intervalMin : CYCLES_PER_DAY[style];

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const amount = Number(cash.replace(/[, ]/g, ''));
      if (!(amount >= 100)) throw new Error('Enter at least 100 of paper money');
      const f = await api.createFund({
        name,
        starting_cash: amount,
        run_now: true,
        config: {
          style,
          interval_minutes: intervalMin,
          universe: tickers,
          max_positions: maxPositions,
          max_position_pct: maxPct,
          cash_reserve_pct: reserve,
          model,
          deep_dive: deepDive,
          use_stop_loss: stopLoss,
          use_take_profit: takeProfit,
          include_news: news,
          market_hours_only: marketHours,
          instructions,
        },
      });
      router.replace(`/funds/${f.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Card>
        <Field label="Fund name" value={name} onChangeText={setName} />
        <Field
          label="Paper money to invest (USD)"
          value={cash}
          onChangeText={setCash}
          keyboardType="decimal-pad"
          hint="Simulated money for this fund's own wallet; your main paper account is untouched. You can add more later."
        />
      </Card>

      <Card>
        <Label style={{ marginBottom: 8 }}>Trading frequency</Label>
        <Chips
          options={catalog.styles.map((s) => ({ label: s.label, value: s.id }))}
          selected={[style]}
          onToggle={(v) => setStyle(v as FundStyle)}
        />
        <Body muted style={{ fontSize: 13, marginTop: 8 }}>
          {STYLE_HINT[style]}
        </Body>
        {style === 'custom' && (
          <Stepper
            label="Minutes between checks"
            value={intervalMin}
            min={15}
            max={1440}
            step={15}
            onChange={setIntervalMin}
          />
        )}
      </Card>

      <Card>
        <Label style={{ marginBottom: 8 }}>Markets to choose from</Label>
        <Chips
          options={Object.keys(catalog.universes).map((u) => ({ label: UNIVERSE_LABELS[u] ?? u, value: u }))}
          selected={universes}
          onToggle={(u) => setUniverses(universes.includes(u) ? universes.filter((x) => x !== u) : [...universes, u])}
        />
        <Field
          style={{ marginTop: space.md }}
          label="Extra tickers (optional)"
          value={extra}
          onChangeText={setExtra}
          autoCapitalize="characters"
          placeholder="NFLX, SHOP, 9984.T"
        />
        <Body muted style={{ fontSize: 12 }}>
          {tickers.length} tickers: {tickers.slice(0, 14).join(', ')}
          {tickers.length > 14 ? '…' : ''}
          {tickers.length > 40 ? '  (max 40)' : ''}
        </Body>
      </Card>

      <Card>
        <Label style={{ marginBottom: 4 }}>Risk limits</Label>
        <Stepper label="Max positions at once" value={maxPositions} min={1} max={20} onChange={setMaxPositions} />
        <Stepper
          label="Max per position"
          value={maxPct}
          min={5}
          max={100}
          step={5}
          format={(v) => `${v}%`}
          onChange={setMaxPct}
        />
        <Stepper
          label="Always keep in cash"
          value={reserve}
          min={0}
          max={50}
          step={5}
          format={(v) => `${v}%`}
          onChange={setReserve}
        />
        <Toggle label="Protective stop-loss on every buy" value={stopLoss} onChange={setStopLoss} />
        <Toggle label="Take profit at Claude's forecast price" value={takeProfit} onChange={setTakeProfit} />
        <Toggle
          label="Only trade while the US market is open"
          hint="Crypto-only funds trade around the clock regardless."
          value={marketHours}
          onChange={setMarketHours}
        />
      </Card>

      <Card>
        <Label style={{ marginBottom: 8 }}>Brain</Label>
        <Segmented
          value={model}
          onChange={setModel}
          options={[
            { label: 'Opus 5.5', value: 'claude-opus-5-5' },
            { label: 'Sonnet 5.5', value: 'claude-sonnet-5-5' },
            { label: 'Haiku 5.5', value: 'claude-haiku-5-5' },
          ]}
        />
        <Toggle label="Read the latest headlines" value={news} onChange={setNews} />
        <Stepper
          label="Full agent-team check on top new buys"
          value={deepDive}
          min={0}
          max={3}
          onChange={setDeepDive}
          format={(v) => (v === 0 ? 'off' : `${v}`)}
        />
        <Body muted style={{ fontSize: 12 }}>
          {deepDive
            ? `Before buying, up to ${deepDive} new pick${deepDive > 1 ? 's go' : ' goes'} through the full TradingAgents team (several minutes and a full analysis's cost each); picks the team does not rate Buy/Overweight are dropped. Best for swing and long-term funds.`
            : 'Each check is one Claude call that sees the whole universe at once.'}
        </Body>
        <Field
          style={{ marginTop: space.md }}
          label="Your instructions (optional)"
          value={instructions}
          onChangeText={setInstructions}
          multiline
          placeholder="e.g. prefer quality large caps, avoid buying right before earnings"
        />
      </Card>

      <Card>
        <Text style={{ color: colors.text, fontWeight: '700' }}>
          {money(Number(cash.replace(/[, ]/g, '')) || 0)} · {tickers.length} tickers · about{' '}
          {perDay >= 1.5 ? `${perDay.toFixed(0)} checks a day` : perDay >= 1 ? 'one check a day' : 'one check a week'}
        </Text>
        <Body muted style={{ fontSize: 12, marginTop: 4 }}>
          Each check is one Claude call: well under a cent with Haiku, roughly $0.10–0.40 with Opus depending on the universe size
          {deepDive ? ', plus the agent-team analyses' : ''}. Your monthly budget in Settings applies.
        </Body>
        <View style={{ marginTop: space.md }}>
          <ErrorBanner message={error} />
        </View>
        <Button
          title="Create fund and make the first trades"
          onPress={create}
          loading={busy}
          disabled={!tickers.length || tickers.length > 40}
          style={{ marginTop: space.sm }}
        />
      </Card>
    </Screen>
  );
}
