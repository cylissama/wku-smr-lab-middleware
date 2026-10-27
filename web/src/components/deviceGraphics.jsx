// Line-art device graphics for the device rail. Everything is drawn in
// currentColor, so the tile's status tone recolors it; .dev-signal parts
// animate only while the device is sending (see App.css).

const STROKE = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.5,
    strokeLinecap: "round",
    strokeLinejoin: "round",
};

const ACCENT = { fill: "currentColor", fillOpacity: 0.14 };

function Frame({ children, label }) {
    return (
        <svg viewBox="0 0 120 90" className="dev-graphic" role="img" aria-label={label}>
            {children}
        </svg>
    );
}

// Emitter arcs, centered at (x, y), opening to the right
function SignalArcs({ x, y }) {
    return (
        <g className="dev-signal" {...STROKE}>
            <path d={`M${x} ${y - 5} a7 7 0 0 1 0 10`} />
            <path d={`M${x + 5} ${y - 10} a13 13 0 0 1 0 20`} />
            <path d={`M${x + 10} ${y - 15} a19 19 0 0 1 0 30`} />
        </g>
    );
}

export function ImuGraphic() {
    return (
        <Frame label="IMU sensor">
            {/* mount plate with bolts */}
            <rect x="14" y="70" width="64" height="8" rx="1.5" {...STROKE} {...ACCENT} />
            <circle cx="20" cy="74" r="1.5" {...STROKE} />
            <circle cx="72" cy="74" r="1.5" {...STROKE} />
            {/* standoffs */}
            <path d="M28 70v-6M64 70v-6" {...STROKE} />
            {/* sensor housing: chamfered box */}
            <path d="M22 64V30l8-8h32l8 8v34z" {...STROKE} {...ACCENT} />
            {/* chip with pins */}
            <rect x="35" y="35" width="22" height="22" rx="1" {...STROKE} />
            <path d="M39 31v4M44 31v4M49 31v4M53 31v4M39 57v4M44 57v4M49 57v4M53 57v4M31 39h4M31 44h4M31 49h4M31 53h4M57 39h4M57 44h4M57 49h4M57 53h4" {...STROKE} strokeWidth={1} />
            <circle cx="46" cy="46" r="4" fill="currentColor" fillOpacity={0.5} />
            {/* axis triad */}
            <g {...STROKE} strokeWidth={1} opacity={0.7}>
                <path d="M8 58V44M8 58h10M8 58l-5 6" />
                <path d="M6 46l2-2 2 2M16 56l2 2-2 2" />
            </g>
            {/* status LED */}
            <circle className="dev-led" cx="64" cy="29" r="2.2" fill="currentColor" />
            <SignalArcs x={84} y={40} />
        </Frame>
    );
}

export function CameraGraphic() {
    return (
        <Frame label="Camera">
            {/* heat-sink fins */}
            <path d="M40 24v-6M48 24v-6M56 24v-6M64 24v-6M72 24v-6" {...STROKE} />
            {/* body */}
            <path d="M30 24h52l4 4v28l-4 4H30z" {...STROKE} {...ACCENT} />
            <path d="M36 30h40" {...STROKE} strokeWidth={1} opacity={0.6} />
            {/* lens barrel */}
            <path d="M30 30h-8l-4 4v16l4 4h8" {...STROKE} />
            <circle cx="16" cy="42" r="9" {...STROKE} {...ACCENT} />
            <circle cx="16" cy="42" r="5" {...STROKE} />
            <circle cx="16" cy="42" r="1.8" fill="currentColor" />
            {/* status LED */}
            <circle className="dev-led" cx="78" cy="52" r="2.2" fill="currentColor" />
            {/* mount bracket and base */}
            <path d="M50 60v8M62 60v8M44 68h24l4 6H40z" {...STROKE} />
            {/* data cable out the back */}
            <path d="M86 42h10q6 0 6 6v26" {...STROKE} strokeWidth={1} opacity={0.5} />
            <path className="dev-signal dev-flow" d="M86 42h10q6 0 6 6v26" {...STROKE} strokeDasharray="3 5" />
        </Frame>
    );
}

export function RobotGraphic() {
    return (
        <Frame label="Robot arm">
            {/* pedestal */}
            <path d="M14 82h44M20 82v-6h32v6" {...STROKE} {...ACCENT} />
            {/* rotating base */}
            <path d="M26 76v-6h20v6" {...STROKE} />
            {/* shoulder */}
            <circle cx="36" cy="62" r="7" {...STROKE} {...ACCENT} />
            <circle cx="36" cy="62" r="2" fill="currentColor" />
            {/* upper arm */}
            <path d="M32 57l14-30M40 59l14-30" {...STROKE} />
            {/* elbow */}
            <circle cx="50" cy="26" r="6" {...STROKE} {...ACCENT} />
            <circle cx="50" cy="26" r="1.8" fill="currentColor" />
            {/* forearm */}
            <path d="M55 22l26 6M54 30l26 4" {...STROKE} />
            {/* wrist */}
            <circle cx="84" cy="32" r="4" {...STROKE} {...ACCENT} />
            {/* gripper */}
            <path d="M88 32h4M92 26v12M92 26h6M92 38h6" {...STROKE} />
            {/* status LED on the base */}
            <circle className="dev-led" cx="46" cy="73" r="2" fill="currentColor" />
            {/* controller cable */}
            <path d="M58 79h30q6 0 6-6v-8" {...STROKE} strokeWidth={1} opacity={0.5} />
            <path className="dev-signal dev-flow" d="M58 79h30q6 0 6-6v-8" {...STROKE} strokeDasharray="3 5" />
            <rect x="88" y="52" width="14" height="13" rx="1" {...STROKE} {...ACCENT} />
            <path d="M91 56h8M91 60h5" {...STROKE} strokeWidth={1} />
        </Frame>
    );
}

export function GenericGraphic() {
    return (
        <Frame label="Device">
            <path d="M30 24h44l8 8v34H30z" {...STROKE} {...ACCENT} />
            <path d="M38 36h28M38 44h20M38 52h24" {...STROKE} strokeWidth={1} />
            <circle className="dev-led" cx="74" cy="58" r="2.2" fill="currentColor" />
            <SignalArcs x={88} y={44} />
        </Frame>
    );
}

const GRAPHICS = { imu: ImuGraphic, camera: CameraGraphic, robot: RobotGraphic };

export function DeviceGraphic({ category }) {
    const Graphic = GRAPHICS[category] ?? GenericGraphic;
    return <Graphic />;
}
