package com.hmall.item.controller;


import com.alibaba.csp.sentinel.annotation.SentinelResource;
import com.alibaba.csp.sentinel.slots.block.BlockException;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.common.exception.CommonException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.item.domain.po.Item;
import com.hmall.item.service.IItemService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "商品管理相关接口")
@Slf4j
@RestController
@RequestMapping("/items")
@RequiredArgsConstructor
public class ItemController {

    private final IItemService itemService;

    @ApiOperation("分页查询商品")
    @GetMapping("/page")
    public PageDTO<ItemDTO> queryItemByPage(PageQuery query) {
        // 1.分页查询
        Page<Item> result = itemService.page(query.toMpPage("update_time", false));
        // 2.封装并返回
        return PageDTO.of(result, ItemDTO.class);
    }

    @ApiOperation("根据id批量查询商品")
    @GetMapping
    public List<ItemDTO> queryItemByIds(@RequestParam("ids") List<Long> ids){
        return itemService.queryItemByIds(ids);
    }

    @ApiOperation("根据id查询商品")
    @GetMapping("{id}")
    @SentinelResource(value = "queryItemById", blockHandler = "queryItemBlocked")
    public ItemDTO queryItemById(@PathVariable("id") Long id) {
        return BeanUtils.copyBean(itemService.getById(id), ItemDTO.class);
    }

    /**
     * 被 Sentinel 限流时的兜底方法。
     *
     * <p>签名要求：参数与原方法一致，末尾多一个 {@link BlockException}；
     * 返回值类型必须与原方法一致。</p>
     */
    public ItemDTO queryItemBlocked(Long id, BlockException ex) {
        log.warn("商品查询被限流 id={} rule={}", id, ex.getRule());
        throw new CommonException("请求过于频繁，请稍后再试", 429);
    }

    @ApiOperation("新增商品")
    @PostMapping
    public void saveItem(@RequestBody ItemDTO item) {
        // 新增
        itemService.save(BeanUtils.copyBean(item, Item.class));
    }

    @ApiOperation("更新商品状态")
    @PutMapping("/status/{id}/{status}")
    public void updateItemStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status){
        Item item = new Item();
        item.setId(id);
        item.setStatus(status);
        itemService.updateById(item);
    }

    @ApiOperation("更新商品")
    @PutMapping
    public void updateItem(@RequestBody ItemDTO item) {
        // 不允许修改商品状态，所以强制设置为null，更新时，就会忽略该字段
        item.setStatus(null);
        // 更新
        itemService.updateById(BeanUtils.copyBean(item, Item.class));
    }

    @ApiOperation("根据id删除商品")
    @DeleteMapping("{id}")
    public void deleteItemById(@PathVariable("id") Long id) {
        itemService.removeById(id);
    }

    @ApiOperation("批量扣减库存")
    @PutMapping("/stock/deduct")
    public void deductStock(@RequestBody List<OrderDetailDTO> items){
        itemService.deductStock(items);
    }

    @ApiOperation("批量回补库存（订单超时关闭时调用）")
    @PutMapping("/stock/restore")
    public void restoreStock(@RequestBody List<OrderDetailDTO> items){
        itemService.restoreStock(items);
    }
}
