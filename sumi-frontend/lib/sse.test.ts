import { expect, test } from "vitest";
import { parseSse } from "./sse";

test("returns the data of every complete event and keeps the unfinished tail", () => {
  expect(parseSse('data: {"a":1}\n\ndata: {"b":2}\n\ndata: {"c')).toEqual({
    payloads: ['{"a":1}', '{"b":2}'],
    rest: 'data: {"c',
  });
});

test("joins multi-line data and ignores comments and other fields", () => {
  expect(parseSse(": ping\nevent: x\ndata: one\ndata:two\n\n")).toEqual({
    payloads: ["one\ntwo"],
    rest: "",
  });
});

test("an empty buffer yields nothing", () => {
  expect(parseSse("")).toEqual({ payloads: [], rest: "" });
});
