import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Region, Run } from "@/lib/graphics/types";

export const fieldClass = "w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm";
export const statusLabel: Record<Region["status"] | Run["status"], string> = {
  unreviewed: "Ungeprüft",
  accept: "Freigegeben",
  retain: "OCR bestätigt",
  defer: "Zurückgestellt",
  queued: "Wartend",
  running: "In Verarbeitung",
  completed: "Abgeschlossen",
  failed: "Fehlgeschlagen",
};

export function Pick<T extends string>({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: ReadonlyArray<readonly [NoInfer<T>, string]>;
}) {
  return (
    <div className="space-y-1 text-sm">
      <span>{label}</span>
      <Select
        value={value}
        onValueChange={(value) => {
          const option = options.find(([key]) => key === value);
          if (option) onChange(option[0]);
        }}
      >
        <SelectTrigger aria-label={label} className="h-10 w-full bg-white">
          <SelectValue>{options.find(([key]) => key === value)?.[1] ?? value}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {options.map(([key, text]) => (
            <SelectItem key={key} value={key}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function sourceLink(value: string | undefined) {
  return value && /^https?:\/\//i.test(value) ? value : undefined;
}
