import React, { useCallback, useEffect, useRef, useState } from 'react';
import { OverlayTrigger, Tooltip } from 'react-bootstrap';

interface Props {
    text: string;
    /** Render in the monospace face used for reference IDs. */
    mono?: boolean;
    className?: string;
    placement?: 'top' | 'bottom' | 'left' | 'right';
}

let nextId = 0;

/**
 * Single-line text that ellipsises when it does not fit its container.
 * The full text is shown in a tooltip on hover or keyboard focus, but only
 * when the text is actually clipped, so short names stay tooltip-free.
 */
export default function TruncatedText({ text, mono, className, placement = 'top' }: Props) {
    const ref = useRef<HTMLSpanElement>(null);
    const [clipped, setClipped] = useState(false);
    const idRef = useRef(`nano-truncate-${++nextId}`);

    const measure = useCallback(() => {
        const el = ref.current;
        if (el) setClipped(el.scrollWidth > el.clientWidth + 1);
    }, []);

    useEffect(() => {
        measure();
        const el = ref.current;
        if (el && typeof ResizeObserver !== 'undefined') {
            const observer = new ResizeObserver(measure);
            observer.observe(el);
            return () => observer.disconnect();
        }
        window.addEventListener('resize', measure);
        return () => window.removeEventListener('resize', measure);
    }, [measure, text]);

    const classes = ['nano-truncate', mono ? 'nano-truncate-mono' : '', className || ''].filter(Boolean).join(' ');

    return (
        <OverlayTrigger
            placement={placement}
            show={clipped ? undefined : false}
            delay={{ show: 200, hide: 0 }}
            overlay={<Tooltip id={idRef.current} className="nano-truncate-tip">{text}</Tooltip>}
        >
            <span ref={ref} className={classes} tabIndex={clipped ? 0 : undefined}>{text}</span>
        </OverlayTrigger>
    );
}
