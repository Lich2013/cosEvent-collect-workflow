import math
import re

class BiliUidMatcher:
    """
    Coser B站 UID 启发式匹配与智能优选服务
    核心特征：零 LLM 额外开销，确定性业务规则，高精度防李鬼
    """
    
    @staticmethod
    def match_coser(weibo_name: str, search_results: list[dict], confidence_threshold: float = 50.0) -> dict:
        """
        根据微博昵称和 B站 用户检索结果，使用启发式多维度算法进行打分优选
        算法指标：名称一致性（满分 50） + 粉丝量级对数评分（满分 30） + 官方认证加权（满分 20）
        
        返回格式:
        {
            "best_match": dict or None,  # 优选出的匹配人信息
            "score": float,              # 优选者的匹配得分
            "candidates": list[dict]     # 所有排好序的候选人详细打分明细
        }
        """
        if not weibo_name or not search_results:
            return {"best_match": None, "score": 0.0, "candidates": []}
            
        ranked_candidates = []
        
        # 移除非字母、非数字及中文字符，标准化比对基础
        def normalize_name(name: str) -> str:
            if not name:
                return ""
            return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", name).lower()
            
        norm_weibo = normalize_name(weibo_name)
        
        for item in search_results:
            uname = item.get("uname") or ""
            mid = item.get("mid")
            fans = int(item.get("fans", 0))
            official_verify = item.get("official_verify") or {}
            verify_type = int(official_verify.get("type", -1))
            verify_desc = official_verify.get("desc") or ""
            usign = item.get("usign") or ""
            
            norm_uname = normalize_name(uname)
            
            # 1. 名字相似度比对 (最高 50 分)
            name_score = 0.0
            if norm_uname == norm_weibo:
                name_score = 50.0
            elif norm_weibo in norm_uname or norm_uname in norm_weibo:
                name_score = 30.0
            else:
                intersection = set(norm_uname).intersection(set(norm_weibo))
                if len(intersection) >= min(len(norm_weibo), len(norm_uname)) * 0.7:
                    name_score = 25.0
                    
            # 2. 签名/认证社交网络互链比对加分 (最高 40 分)
            social_score = 0.0
            if weibo_name and (weibo_name.lower() in usign.lower() or weibo_name.lower() in verify_desc.lower()):
                social_score = 40.0
                
            # 过滤完全无关联的候选人，防止高噪声干扰
            if name_score == 0.0 and social_score == 0.0:
                continue
                
            # 3. 粉丝量级对数计算 (最高约 30 分)
            fans_score = math.log10(max(fans, 1)) * 5.0
            fans_score = min(fans_score, 30.0)
            
            # 4. 官方认证加权分 (最高 20 分)
            verify_score = 0.0
            if verify_type != -1 or verify_desc:
                verify_score = 20.0
                
            total_score = name_score + fans_score + verify_score + social_score
            
            ranked_candidates.append({
                "uname": uname,
                "mid": mid,
                "fans": fans,
                "verify_desc": verify_desc,
                "scores": {
                    "name": name_score,
                    "fans": fans_score,
                    "verify": verify_score,
                    "social": social_score,
                    "total": round(total_score, 2)
                }
            })
            
        # 按得分从高到低排序
        ranked_candidates.sort(key=lambda x: x["scores"]["total"], reverse=True)
        
        # 寻找首选高信度最佳匹配
        best_match = None
        best_score = 0.0
        
        for cand in ranked_candidates:
            score = cand["scores"]["total"]
            
            # 绿色放行免检通道：精确匹配 (50分) 且拥有官方认证 (20分) 的真实新人
            is_green_bypass = (cand["scores"]["name"] == 50.0 and cand["scores"]["verify"] == 20.0)
            
            # 安全门槛校验：得分超过置信度阈值，且符合 粉丝合理(>=100) 或 处于绿色通道
            if score >= confidence_threshold and (cand["fans"] >= 100 or is_green_bypass):
                best_match = cand
                best_score = score
                break
                
        return {
            "best_match": best_match,
            "score": best_score,
            "candidates": ranked_candidates
        }
