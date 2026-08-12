#!/bin/sh
# verify.sh — decode PNGs whose pixels are known, and compare byte for byte.
#
#   MERE=/path/to/mere sh verify.sh
#
# The images come from test/make_pngs.py, which computes the pixels and so also
# computes the answer. That is what makes this a check rather than a demo: the
# expected PPM is derived from the same numbers the PNG was built from, not from
# a previous run of this decoder.
#
# What the cases cover, and why each one is there:
#
#   rgb_filter0..4   one filter per file, so a broken filter names itself
#   rgb_mixed        filters mixed down the image, which is what encoders do —
#                    each row is reconstructed against the row above it, itself
#                    already reconstructed
#   grey_mixed       one channel per pixel: `left` is one byte back, not three
#   rgba_mixed       four channels, alpha dropped on the way out
#   rgb_split_idat   the zlib stream split across two IDAT chunks. A decoder that
#                    inflates each chunk on its own passes everything above and
#                    fails this
set -e

MERE="${MERE:-mere}"
DIR="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 "$DIR/test/make_pngs.py" "$TMP" > "$TMP/cases"

pass=0
fail=0
while read -r name; do
  png="$TMP/$name"
  # A `refuse_` case has no right answer: what is being checked is that mpng says
  # so rather than decoding it into something plausible and wrong.
  case "$name" in
    refuse_*)
      if "$MERE" "$DIR/mpng.mere" ppm "$png" "$TMP/x.ppm" 2>&1 | grep -q "not supported"; then
        printf '  ok    %s is refused, not guessed at\n' "$name"
        pass=$((pass + 1))
      else
        printf '  FAIL  %s was not refused\n' "$name"
        fail=$((fail + 1))
      fi
      continue
      ;;
  esac
  if "$MERE" "$DIR/mpng.mere" ppm "$png" "$TMP/got.ppm" > /dev/null 2>"$TMP/err"; then
    if cmp -s "$TMP/got.ppm" "$png.expected"; then
      printf '  ok    %s\n' "$name"
      pass=$((pass + 1))
    else
      printf '  FAIL  %s (decoded %s bytes, expected %s)\n' "$name" \
        "$(wc -c < "$TMP/got.ppm" | tr -d ' ')" \
        "$(wc -c < "$png.expected" | tr -d ' ')"
      # Where they first differ says which scanline went wrong, which is more
      # use than the fact that they differ.
      cmp "$TMP/got.ppm" "$png.expected" 2>&1 | sed 's/^/        /' || true
      fail=$((fail + 1))
    fi
  else
    printf '  FAIL  %s did not decode\n' "$name"
    sed 's/^/        /' "$TMP/err"
    fail=$((fail + 1))
  fi
done < "$TMP/cases"

# Encode, decode, and see if the pixels survived the trip. That exercises the
# filter *choice* — the encoder tries all five per row and keeps the cheapest —
# and the zlib and CRC it writes, against this project's own reader.
for name in rgb_mixed.png rgb_split_idat.png; do
  png="$TMP/$name"
  "$MERE" "$DIR/mpng.mere" ppm "$png" "$TMP/rt_in.ppm" > /dev/null
  "$MERE" "$DIR/mpng.mere" encode "$TMP/rt_in.ppm" "$TMP/rt.png" > /dev/null
  "$MERE" "$DIR/mpng.mere" ppm "$TMP/rt.png" "$TMP/rt_out.ppm" > /dev/null
  if cmp -s "$TMP/rt_in.ppm" "$TMP/rt_out.ppm"; then
    printf '  ok    %s survives encode and decode\n' "$name"
    pass=$((pass + 1))
  else
    printf '  FAIL  %s changed on the round trip\n' "$name"
    fail=$((fail + 1))
  fi
done

# The backends have to agree. They did not, once: writing the PPM through
# `print_no_nl` dropped every zero byte in the compiled backends and kept them in
# the interpreter, so the same image decoded to two different files. Nothing but
# running both and comparing would have caught it — see PAIN.md.
if [ -n "$CC_CHECK" ] && command -v clang >/dev/null 2>&1; then
  "$MERE" -c "$DIR/mpng.mere" > "$TMP/mpng.c"
  clang -O2 -w "$TMP/mpng.c" -o "$TMP/mpng_c"
  while read -r name; do
    png="$TMP/$name"
    case "$name" in
      refuse_*)
        if "$TMP/mpng_c" ppm "$png" "$TMP/x.ppm" 2>&1 | grep -q "not supported"; then
          printf '  ok    %s is refused (compiled)\n' "$name"
          pass=$((pass + 1))
        else
          printf '  FAIL  %s was not refused once compiled\n' "$name"
          fail=$((fail + 1))
        fi
        continue
        ;;
    esac
    "$TMP/mpng_c" ppm "$png" "$TMP/c.ppm" > /dev/null
    if cmp -s "$TMP/c.ppm" "$png.expected"; then
      printf '  ok    %s (compiled)\n' "$name"
      pass=$((pass + 1))
    else
      printf '  FAIL  %s decoded differently once compiled\n' "$name"
      fail=$((fail + 1))
    fi
  done < "$TMP/cases"
fi

echo "verify: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
