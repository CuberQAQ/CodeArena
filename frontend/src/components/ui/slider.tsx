/**
 * Dual-handle range slider built on @base-ui/react Slider.
 *
 * Supports single value (number) and range (array of two numbers) modes.
 * Uses Tailwind + CSS custom properties for styling, matching the project's
 * dark/light theme tokens.
 */

import { Slider as SliderPrimitive } from "@base-ui/react/slider";
import { cn } from "@/lib/utils";

// Re-export sub-components for advanced usage
const SliderRoot = SliderPrimitive.Root;
const SliderControl = SliderPrimitive.Control;
const SliderTrack = SliderPrimitive.Track;
const SliderIndicator = SliderPrimitive.Indicator;
const SliderThumb = SliderPrimitive.Thumb;

export interface SliderProps {
  /** The value: a single number or [min, max] array */
  value: number | [number, number];
  /** Called on every value change (drag, keyboard, click) */
  onValueChange?: (value: number | [number, number]) => void;
  /** Called when drag/interaction ends -- use this to trigger API calls */
  onValueCommitted?: (value: number | [number, number]) => void;
  /** Minimum value */
  min?: number;
  /** Maximum value */
  max?: number;
  /** Step increment */
  step?: number;
  /** Whether the slider is disabled */
  disabled?: boolean;
  /** Additional class name for the root element */
  className?: string;
  /** aria-label for the slider thumbs */
  "aria-label"?: string;
}

/**
 * A styled dual-handle range slider.
 *
 * ```tsx
 * <Slider
 *   value={[minVal, maxVal]}
 *   onValueChange={setRange}
 *   onValueCommitted={handleCommit}
 *   min={800} max={3000} step={50}
 * />
 * ```
 */
export function Slider({
  value,
  onValueChange,
  onValueCommitted,
  min = 0,
  max = 100,
  step = 1,
  disabled = false,
  className,
  ...props
}: SliderProps) {
  const isRange = Array.isArray(value);

  return (
    <SliderRoot
      value={value as number | readonly number[]}
      onValueChange={(v: number | readonly number[]) => {
        if (isRange) {
          onValueChange?.(v as [number, number]);
        } else {
          onValueChange?.(v as number);
        }
      }}
      onValueCommitted={(v: number | readonly number[]) => {
        if (isRange) {
          onValueCommitted?.(v as [number, number]);
        } else {
          onValueCommitted?.(v as number);
        }
      }}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      className={cn("relative flex w-full touch-none select-none items-center", className)}
    >
      <SliderControl className="relative h-5 w-full cursor-pointer">
        <SliderTrack className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-muted">
          <SliderIndicator className="absolute h-full rounded-full bg-primary data-[disabled]:opacity-50" />
        </SliderTrack>
        {isRange ? (
          <>
            <SliderThumb
              index={0}
              className="block size-4 rounded-full border-2 border-primary bg-background shadow-md transition-[box-shadow,transform] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-110 disabled:pointer-events-none disabled:opacity-50 data-[dragging]:scale-110 data-[dragging]:shadow-lg"
              getAriaLabel={(index) =>
                props["aria-label"]
                  ? `${props["aria-label"]} ${index + 1}`
                  : `Slider thumb ${index + 1}`
              }
            />
            <SliderThumb
              index={1}
              className="block size-4 rounded-full border-2 border-primary bg-background shadow-md transition-[box-shadow,transform] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-110 disabled:pointer-events-none disabled:opacity-50 data-[dragging]:scale-110 data-[dragging]:shadow-lg"
              getAriaLabel={(index) =>
                props["aria-label"]
                  ? `${props["aria-label"]} ${index + 1}`
                  : `Slider thumb ${index + 1}`
              }
            />
          </>
        ) : (
          <SliderThumb
            className="block size-4 rounded-full border-2 border-primary bg-background shadow-md transition-[box-shadow,transform] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-110 disabled:pointer-events-none disabled:opacity-50 data-[dragging]:scale-110 data-[dragging]:shadow-lg"
            getAriaLabel={() => props["aria-label"] ?? "Slider thumb"}
          />
        )}
      </SliderControl>
    </SliderRoot>
  );
}
