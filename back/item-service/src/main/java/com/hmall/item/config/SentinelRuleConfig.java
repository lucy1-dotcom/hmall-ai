package com.hmall.item.config;

import com.alibaba.csp.sentinel.slots.block.RuleConstant;
import com.alibaba.csp.sentinel.slots.block.flow.FlowRule;
import com.alibaba.csp.sentinel.slots.block.flow.FlowRuleManager;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;

import javax.annotation.PostConstruct;
import java.util.Collections;

/**
 * Sentinel 流控规则（代码方式加载）。
 *
 * <p>生产环境更推荐把规则放到 Nacos 配置中心（sentinel-datasource-nacos），
 * 这样在 dashboard 改完能持久化；这里用代码加载是为了让项目“开箱即跑”，
 * 不依赖 dashboard 是否启动。</p>
 *
 * <p>阈值可通过 {@code hm.sentinel.flow.qps} 配置，压测时调大即可，
 * 比如 {@code --hm.sentinel.flow.qps=1000}。</p>
 */
@Slf4j
@Configuration
public class SentinelRuleConfig {

    @Value("${hm.sentinel.flow.qps:2}")
    private double qps;

    @PostConstruct
    public void initFlowRules() {
        FlowRule rule = new FlowRule();
        rule.setResource("queryItemById");
        rule.setGrade(RuleConstant.FLOW_GRADE_QPS);
        rule.setCount(qps);
        FlowRuleManager.loadRules(Collections.singletonList(rule));
        log.info("Sentinel 流控规则已加载：queryItemById -> QPS={}", qps);
    }
}
