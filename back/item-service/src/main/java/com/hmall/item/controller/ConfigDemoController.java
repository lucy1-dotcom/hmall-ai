package com.hmall.item.controller;

import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Nacos 配置中心热更新的演示接口。
 *
 * <p>{@code @RefreshScope} 会让这个 Bean 变成「作用域代理」：当 Nacos 推送配置变更时，
 * Spring Cloud 发布 {@code RefreshScopeRefreshedEvent}，该作用域内的 Bean 被销毁重建，
 * {@code @Value} 随之重新注入——**不需要重启服务**。</p>
 *
 * <p>演示方式：在 Nacos 控制台修改 {@code item-service.yaml} 里的
 * {@code hm.demo.message}，几秒后刷新本接口即可看到新值。</p>
 */
@Api(tags = "Nacos 配置热更新演示")
@RefreshScope
@RestController
@RequestMapping("/config")
public class ConfigDemoController {

    @Value("${hm.demo.message:未从配置中心读取到}")
    private String message;

    @Value("${hm.demo.limit:0}")
    private int limit;

    @ApiOperation("查看当前生效的配置值")
    @GetMapping("/demo")
    public Map<String, Object> demo() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("message", message);
        result.put("limit", limit);
        result.put("tips", "去 Nacos 改 item-service.yaml 的 hm.demo.message，几秒后刷新本接口");
        return result;
    }
}
