export class HttpError extends Error {
  public constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "HttpError";
  }
}
