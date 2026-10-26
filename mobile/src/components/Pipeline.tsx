import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { colors, radius, space } from '../lib/theme';
import type { AgentStatus } from '../lib/types';

const TEAM_ORDER = ['Analyst Team', 'Research Team', 'Trading Team', 'Risk Management', 'Portfolio Management'];

const TEAM_BLURB: Record<string, string> = {
  'Analyst Team': 'Read prices, indicators, news, social posts and financials, in parallel',
  'Research Team': 'A bull and a bear argue the case; the research manager rules',
  'Trading Team': 'Turns the plan into a concrete trade: entry, stop, size',
  'Risk Management': 'Aggressive, conservative and neutral analysts stress-test the trade',
  'Portfolio Management': 'Makes the final 5-tier call against your portfolio',
};

/** The TradingAgents firm as a live org chart: each agent lights up as it works. */
export function Pipeline({ agents, teams }: { agents: Record<string, AgentStatus>; teams: Record<string, string> }) {
  return (
    <View style={{ gap: space.md }}>
      {TEAM_ORDER.map((team, ti) => {
        const members = Object.keys(agents).filter((a) => teams[a] === team);
        if (!members.length) return null;
        const done = members.every((m) => agents[m] === 'completed');
        const active = members.some((m) => agents[m] === 'in_progress');
        return (
          <View key={team} style={{ flexDirection: 'row', gap: space.md }}>
            <View style={{ alignItems: 'center' }}>
              <View
                style={[
                  st.dot,
                  done && { backgroundColor: colors.up, borderColor: colors.up },
                  active && { borderColor: colors.accent },
                ]}
              >
                {active ? <ActivityIndicator size="small" color={colors.accent} /> : null}
                {done ? <Text style={{ color: colors.bg, fontWeight: '900', fontSize: 12 }}>✓</Text> : null}
              </View>
              {ti < TEAM_ORDER.length - 1 ? <View style={st.line} /> : null}
            </View>
            <View style={{ flex: 1, paddingBottom: space.sm }}>
              <Text style={[st.team, active && { color: colors.accent }]}>{team}</Text>
              <Text style={st.blurb}>{TEAM_BLURB[team]}</Text>
              <View style={st.members}>
                {members.map((m) => (
                  <View
                    key={m}
                    style={[
                      st.member,
                      agents[m] === 'completed' && { borderColor: `${colors.up}88`, backgroundColor: `${colors.up}14` },
                      agents[m] === 'in_progress' && {
                        borderColor: colors.accent,
                        backgroundColor: `${colors.accent}1F`,
                      },
                    ]}
                  >
                    <Text
                      style={[
                        st.memberText,
                        agents[m] === 'pending' && { color: colors.faint },
                        agents[m] === 'in_progress' && { color: colors.accent },
                      ]}
                    >
                      {m.replace(' Analyst', '').replace(' Researcher', '')}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          </View>
        );
      })}
    </View>
  );
}

const st = StyleSheet.create({
  dot: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  line: { width: 2, flex: 1, backgroundColor: colors.border, marginTop: 2 },
  team: { color: colors.text, fontWeight: '700', fontSize: 15 },
  blurb: { color: colors.muted, fontSize: 12, marginTop: 2, marginBottom: 8, lineHeight: 17 },
  members: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  member: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  memberText: { color: colors.text, fontSize: 12, fontWeight: '600' },
});
