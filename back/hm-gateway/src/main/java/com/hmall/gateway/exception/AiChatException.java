package com.hmall.gateway.exception;

/**
 * 调用 Python AI 服务失败（连不上、返回非 2xx、解析异常）。
 */
public class AiChatException extends RuntimeException {

    private final int status;

    public AiChatException(int status, String message) {
        super(message);
        this.status = status;
    }

    public AiChatException(String message, Throwable cause) {
        super(message, cause);
        this.status = 502;
    }

    public int getStatus() {
        return status;
    }
}
