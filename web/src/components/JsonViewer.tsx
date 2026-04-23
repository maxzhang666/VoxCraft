interface Props {
  data: unknown;
  maxHeight?: number;
}

export function JsonViewer({ data, maxHeight = 300 }: Props) {
  return (
    <pre
      style={{
        fontFamily:
          "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace",
        fontSize: 12,
        lineHeight: 1.6,
        padding: "var(--vc-spacing-md)",
        backgroundColor: "var(--vc-color-bg-secondary)",
        borderRadius: "var(--vc-radius-sm)",
        maxHeight,
        overflow: "auto",
        margin: 0,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
