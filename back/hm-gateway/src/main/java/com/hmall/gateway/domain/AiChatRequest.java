package com.hmall.gateway.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;

/**
 * 前端发来的对话请求。
 *
 * <p>字段名和 Python 侧 AgentChatRequest 保持一致（snake_case），
 * 这样网关不需要做任何转换，直接把对象转发过去。</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class AiChatRequest {

    /** 当前登录用户 id */
    @NotNull(message = "user_id 不能为空")
    @JsonProperty("user_id")
    private Long userId;

    /** 用户的话 */
    @NotBlank(message = "message 不能为空")
    @Size(max = 2000, message = "message 最长 2000 字")
    private String message;

    /** 会话 id，前端首次不传，由 AI 服务生成并通过 meta 事件返回 */
    @JsonProperty("session_id")
    private String sessionId;
}
