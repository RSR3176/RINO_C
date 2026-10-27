export function BrandMark({ size = 52 }: { size?: number }) {
  return (
    <div
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.3),
        background: "#4338CA",
        boxShadow: `inset -${Math.round(size * 0.3)}px -${Math.round(size * 0.3)}px 0 #818CF8`,
      }}
    />
  );
}
