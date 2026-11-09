package com.hmall.trade.config;

import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRule;
import com.alibaba.csp.sentinel.slots.block.degrade.DegradeRuleManager;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Configuration;

import javax.annotation.PostConstruct;
import java.util.Collections;

/**
 * Sentinel 熔断降级规则。
 *
 * <p>下单链路依赖 item-service（查商品、扣库存）。当商品服务不可用或异常率升高时，
 * 熔断器打开，后续请求直接走 {@code fallback}，避免线程被慢调用拖死（防止级联雪崩）。</p>
 *
 * <p>规则：资源 {@code createOrder} 在 10 秒统计窗口内，请求数 ≥ 5 且异常比例超过 50%，
 * 触发熔断 10 秒；之后放行一个探测请求，成功则恢复。</p>
 */
@Slf4j
@Configuration
public class SentinelRuleConfig {

    @PostConstruct
    public void initDegradeRules() {
        DegradeRule rule = new DegradeRule();
        rule.setResource("createOrder");
        rule.setGrade(RuleConstant.DEGRADE_GRADE_EXCEPTION_RATIO);
        rule.setCount(0.5);
        rule.setTimeWindow(10);
        rule.setMinRequestAmount(5);
        rule.setStatIntervalMs(10_000);
        DegradeRuleManager.loadRules(Collections.singletonList(rule));
        log.info("Sentinel 熔断规则已加载：createOrder -> 异常比例>50% 熔断 10s");
    }
}
