import { Fragment, type ReactNode } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, space } from '../lib/theme';

// A small markdown renderer for the agents' reports: headings, bullet and
// numbered lists, bold/italic/code spans, rules, quotes and tables. Enough for
// what the models write, without a native dependency.

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('**') || tok.startsWith('__')) {
      out.push(
        <Text key={`${key}-${i++}`} style={s.bold}>
          {tok.slice(2, -2)}
        </Text>,
      );
    } else if (tok.startsWith('`')) {
      out.push(
        <Text key={`${key}-${i++}`} style={s.code}>
          {tok.slice(1, -1)}
        </Text>,
      );
    } else {
      out.push(
        <Text key={`${key}-${i++}`} style={s.italic}>
          {tok.slice(1, -1)}
        </Text>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Table({ rows, k }: { rows: string[]; k: string }) {
  const cells = rows
    .filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r))
    .map((r) =>
      r
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((c) => c.trim()),
    );
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginVertical: space.sm }}>
      <View style={s.table}>
        {cells.map((row, ri) => (
          <View key={`${k}-r${ri}`} style={[s.tr, ri === 0 && { backgroundColor: colors.surfaceAlt }]}>
            {row.map((c, ci) => (
              <Text key={`${k}-c${ci}`} style={[s.td, ri === 0 && s.bold]}>
                {inline(c, `${k}-${ri}-${ci}`)}
              </Text>
            ))}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

export function Markdown({ children }: { children: string }) {
  const lines = (children || '').replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let para: string[] = [];
  let i = 0;
  const flush = () => {
    if (para.length) {
      const k = `p${blocks.length}`;
      blocks.push(
        <Text key={k} style={s.p}>
          {inline(para.join(' '), k)}
        </Text>,
      );
      para = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    const k = `b${blocks.length}`;
    if (!trimmed) {
      flush();
      i++;
      continue;
    }
    if (trimmed.startsWith('|')) {
      flush();
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(lines[i++]);
      blocks.push(<Table key={k} rows={rows} k={k} />);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (h) {
      flush();
      const level = h[1].length;
      blocks.push(
        <Text key={k} style={[s.h, level <= 2 ? s.h1 : level === 3 ? s.h2 : s.h3]}>
          {inline(h[2].replace(/#+$/, '').trim(), k)}
        </Text>,
      );
      i++;
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flush();
      blocks.push(<View key={k} style={s.hr} />);
      i++;
      continue;
    }
    const li = /^(\s*)([-*+•]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      flush();
      const depth = Math.min(3, Math.floor(li[1].length / 2));
      const bullet = /\d/.test(li[2]) ? li[2] : '•';
      blocks.push(
        <View key={k} style={[s.li, { paddingLeft: depth * 14 }]}>
          <Text style={s.bullet}>{bullet}</Text>
          <Text style={[s.p, { flex: 1, marginBottom: 0 }]}>{inline(li[3], k)}</Text>
        </View>,
      );
      i++;
      continue;
    }
    if (trimmed.startsWith('>')) {
      flush();
      blocks.push(
        <View key={k} style={s.quote}>
          <Text style={[s.p, { color: colors.muted }]}>{inline(trimmed.replace(/^>\s?/, ''), k)}</Text>
        </View>,
      );
      i++;
      continue;
    }
    para.push(trimmed);
    i++;
  }
  flush();
  return <Fragment>{blocks}</Fragment>;
}

const s = StyleSheet.create({
  p: { color: colors.text, fontSize: 15, lineHeight: 22, marginBottom: space.sm },
  bold: { fontWeight: '700', color: colors.text },
  italic: { fontStyle: 'italic' },
  code: { fontFamily: 'Courier', backgroundColor: colors.surfaceAlt, color: colors.info },
  h: { color: colors.text, fontWeight: '700', marginTop: space.md, marginBottom: space.sm },
  h1: { fontSize: 19 },
  h2: { fontSize: 17 },
  h3: { fontSize: 15, color: colors.accent },
  hr: { height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginVertical: space.md },
  li: { flexDirection: 'row', gap: 8, marginBottom: 6 },
  bullet: { color: colors.accent, fontSize: 15, lineHeight: 22, minWidth: 14 },
  quote: { borderLeftWidth: 3, borderLeftColor: colors.border, paddingLeft: space.md, marginBottom: space.sm },
  table: { borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, borderRadius: 6 },
  tr: { flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  td: { color: colors.text, fontSize: 13, paddingHorizontal: 8, paddingVertical: 6, width: 130 },
});
