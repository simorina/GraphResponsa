import React from 'react';

interface SigilloProps {
  className?: string;
  /** Disegna le torri tratto per tratto all'ingresso. Solo dove si vede grande. */
  animato?: boolean;
}

/**
 * Lo stemma ridotto a marca: i tre monti del Titano - la Guaita, la Cesta e il
 * Montale - ciascuno con la sua torre, e le tre penne nell'oro della corona.
 * Il filetto di base e' il cartiglio.
 */
export const Sigillo: React.FC<SigilloProps> = ({
  className = 'h-[18px] w-[18px]',
  animato = false,
}) => {
  const torre = (d: string, i: number) => (
    <path
      key={d}
      d={d}
      className={animato ? 'traccia' : undefined}
      style={animato ? ({ ['--lung' as string]: 26, ['--i' as string]: i } as React.CSSProperties) : undefined}
    />
  );

  return (
    <svg viewBox="0 0 20 20" className={className} aria-hidden="true">
      <g
        className="fill-none stroke-azzurro"
        strokeWidth="1.15"
        strokeLinejoin="round"
        strokeLinecap="round"
      >
        {torre('M4.5 15.1V9.5L6 7.9l1.5 1.6v5.6', 0)}
        {torre('M8.8 15.1V7.5L10.3 5.9l1.5 1.6v7.6', 1)}
        {torre('M13.1 15.1V10.4l1.4-1.5 1.4 1.5v4.7', 2)}
      </g>

      <g className="fill-dorato-2">
        <circle cx="6" cy="6.5" r="0.8" className={animato ? 'rise' : undefined}
                style={animato ? ({ ['--i' as string]: 4 } as React.CSSProperties) : undefined} />
        <circle cx="10.3" cy="4.5" r="0.8" className={animato ? 'rise' : undefined}
                style={animato ? ({ ['--i' as string]: 5 } as React.CSSProperties) : undefined} />
        <circle cx="14.5" cy="7.5" r="0.8" className={animato ? 'rise' : undefined}
                style={animato ? ({ ['--i' as string]: 6 } as React.CSSProperties) : undefined} />
      </g>

      <path
        d="M3.3 15.9h13.4"
        className={`stroke-dorato-2 ${animato ? 'traccia' : ''}`}
        style={animato ? ({ ['--lung' as string]: 14, ['--i' as string]: 3 } as React.CSSProperties) : undefined}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
};
