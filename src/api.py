import orjson
from aiohttp import web
from loguru import logger
from rapidfuzz import fuzz

from . import models
from .config import settings
from .redis_client import redis_client
from .utils import normalize_title, append_trackers_to_magnet

routes = web.RouteTableDef()

def json_response(data, status=200):
    return web.Response(
        text=orjson.dumps(data).decode('utf-8'),
        status=status,
        content_type='application/json'
    )

@routes.get('/manifest.json')
async def manifest(request):
    return json_response(models.Manifest().model_dump())

@routes.get('/health')
async def health(request):
    return json_response({"status": "ok"})

@routes.get('/catalog/{type}/{id}.json')
async def catalog(request):
    # page = int(request.query.get('page', 1)) # For future pagination
    show_ids = await redis_client.smembers("catalog:series")
    
    if not show_ids:
        return json_response(models.CatalogResponse(metas=[]).model_dump())

    pipe = redis_client.pipeline()
    for show_id in show_ids:
        pipe.hgetall(f"show:{show_id}")
    
    results = await pipe.execute()
    
    metas = []
    for show_data in results:
        if show_data:
            metas.append(models.Meta(
                id=show_data['id'],
                name=show_data['name'],
                type='series'
            ))
    
    metas.sort(key=lambda x: x.name)
    return json_response(models.CatalogResponse(metas=metas).model_dump())

@routes.get('/meta/{type}/{id}.json')
async def meta(request):
    show_id = request.match_info['id']
    
    show_data = await redis_client.hgetall(f"show:{show_id}")
    if not show_data:
        return web.Response(status=404)

    # Find all seasons for this show
    season_keys = [key async for key in redis_client.scan_iter(f"season:{show_id}:*")]
    
    videos = []
    pipe = redis_client.pipeline()
    for season_key in season_keys:
        pipe.zrange(season_key, 0, -1)
    
    season_episodes_data = await pipe.execute()
    
    for i, season_key in enumerate(season_keys):
        season_num = int(season_key.split(':')[-1])
        episode_data = season_episodes_data[i]
        
        for ep_res in episode_data:
            ep, res = ep_res.split(':')
            videos.append(models.Video(
                id=f"{show_id}:{season_num}:{ep}",
                title=f"Episode {ep}",
                season=season_num,
                episode=int(ep)
            ))
    
    # Sort videos by season then episode
    videos.sort(key=lambda v: (v.season, v.episode))

    meta_obj = models.Meta(
        id=show_id,
        name=show_data.get('name', 'Unknown'),
        poster=show_data.get('poster'),
        videos=videos,
    )
    return json_response(models.MetaResponse(meta=meta_obj).model_dump())


@routes.get('/stream/{type}/{id}.json')
async def stream(request):
    show_id, season, episode = request.match_info['id'].split(':')
    
    episode_key = f"episode:season:{show_id}:{season}:{episode}"
    episode_data = await redis_client.hgetall(episode_key)
    
    if not episode_data:
        return json_response(models.StreamsResponse().model_dump())
    
    trackers = await redis_client.lrange("trackers:latest", 0, -1)
    magnet = append_trackers_to_magnet(episode_data['magnet'], trackers)
    
    stream_obj = models.Stream(
        name=f"TamilBlasters {episode_data['resolution']}",
        title=f"S{int(season):02d}E{int(episode):02d} - {episode_data['resolution']}\n"
              f"🗣️ {episode_data['languages']} 💾 {episode_data['size']}",
        url=magnet
    )
    return json_response(models.StreamsResponse(streams=[stream_obj]).model_dump())

@routes.get('/search')
async def search(request):
    query = request.query.get('q')
    if not query:
        return json_response(models.CatalogResponse(metas=[]).model_dump())

    normalized_query = normalize_title(query)
    
    show_ids = await redis_client.smembers("catalog:series")
    matches = []
    
    for show_id in show_ids:
        # tb:show_name_2023 -> show name 2023
        title_from_id = show_id.replace("tb:", "").replace("_", " ")
        normalized_title = normalize_title(title_from_id)
        
        score = fuzz.WRatio(normalized_query, normalized_title, score_cutoff=85)
        if score >= 85:
            matches.append({'id': show_id, 'score': score})

    if not matches:
        return json_response(models.CatalogResponse(metas=[]).model_dump())
    
    # Sort by score descending
    matches.sort(key=lambda x: x['score'], reverse=True)
    
    pipe = redis_client.pipeline()
    for match in matches:
        pipe.hgetall(f"show:{match['id']}")

    results = await pipe.execute()
    metas = []
    for show_data in results:
        if show_data:
            metas.append(models.Meta(id=show_data['id'], name=show_data['name'], type='series'))

    return json_response(models.CatalogResponse(metas=metas).model_dump())

@routes.get('/debug/streams/{show_id}')
async def debug_streams(request):
    show_id = request.match_info['id']
    keys = [key async for key in redis_client.scan_iter(f"episode:season:{show_id}:*")]
    
    pipe = redis_client.pipeline()
    for key in keys:
        pipe.hgetall(key)
    
    results = await pipe.execute()
    return json_response({"keys_found": len(keys), "streams": results})
    
@routes.get('/debug/redis/{key:.*}')
async def debug_redis(request):
    key = request.match_info['key']
    key_type = await redis_client.type(key)
    
    data = None
    if key_type == 'hash':
        data = await redis_client.hgetall(key)
    elif key_type == 'zset':
        data = await redis_client.zrange(key, 0, -1, withscores=True)
    elif key_type == 'list':
        data = await redis_client.lrange(key, 0, -1)
    elif key_type == 'set':
        data = await redis_client.smembers(key)
    elif key_type == 'string':
        data = await redis_client.get(key)
    else:
        data = "Key not found or unsupported type"
        
    return json_response({
        "key": key,
        "type": key_type,
        "value": data
    })
